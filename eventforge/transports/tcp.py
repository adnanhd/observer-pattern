"""TCP transport for cross-process / cross-machine messaging.

Uses length-prefixed JSON over TCP sockets. Each message on the wire:
    [4 bytes big-endian length][JSON payload]

Two classes:
    TCPServerTransport — listens for client connections, dispatches messages
    TCPClientTransport — connects to a server, sends/receives messages

Both implement the Transport ABC, so they plug into MessageQueue and
RPCServer/RPCClient unchanged.
"""

from __future__ import annotations
from typing import Dict, List, Optional

import asyncio
import fnmatch
import json
import logging
import socket
import struct
import threading
from collections import defaultdict
from collections.abc import Callable
from queue import Empty, Queue
from uuid import uuid4

from eventforge.transports.base import Transport
from eventforge.types import Message

logger = logging.getLogger(__name__)

_HEADER_FMT = "!I"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


def _send_msg(sock: socket.socket, data: bytes) -> None:
    """Send a length-prefixed message."""
    sock.sendall(struct.pack(_HEADER_FMT, len(data)) + data)


def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    """Receive exactly n bytes. Returns None on disconnect."""
    chunks: List[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_msg(sock: socket.socket) -> Optional[bytes]:
    """Receive a length-prefixed message. Returns None on disconnect."""
    header = _recv_exact(sock, _HEADER_SIZE)
    if header is None:
        return None
    (length,) = struct.unpack(_HEADER_FMT, header)
    return _recv_exact(sock, length)


def _serialize(msg: Message) -> bytes:
    return json.dumps(msg.model_dump(mode="json")).encode()


def _deserialize(data: bytes) -> Message:
    return Message(**json.loads(data))


def _topic_matches(topic: str, pattern: str) -> bool:
    if pattern == topic:
        return True
    return fnmatch.fnmatch(topic, pattern)


class TCPServerTransport(Transport):
    """TCP server transport -- accepts connections, dispatches messages.

    .. warning::

       This transport ships **no authentication and no transport
       encryption**. Default ``host="127.0.0.1"`` keeps the listener
       bound to loopback so reverse-proxy / SSH-tunnel patterns are
       the path to multi-host setups. Do not pass ``host="0.0.0.0"``
       unless the network reachable from that address is one you
       trust to invoke arbitrary registered RPC methods. See
       ``SECURITY.md``.

    Usage::

        transport = TCPServerTransport(host="127.0.0.1", port=9090)
        transport.start()
        queue = MessageQueue(transport=transport)
        rpc = RPCServer(queue, service_name="myservice")
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9090) -> None:
        self._host = host
        self._port = port
        self._server_sock: Optional[socket.socket] = None
        self._running = False
        self._accept_thread: Optional[threading.Thread] = None
        self._clients: List[socket.socket] = []
        self._subscribers: Dict[str, Callable[[Message], None]] = {}
        self._topic_subs: Dict[str, List[str]] = defaultdict(list)
        self._queues: Dict[str, Queue[Message]] = defaultdict(Queue)
        self._lock = threading.RLock()

    def start(self) -> None:
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self._host, self._port))
        self._server_sock.listen(16)
        self._server_sock.settimeout(1.0)
        self._running = True
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        logger.info("TCP server listening on %s:%d", self._host, self._port)

    def close(self) -> None:
        self._running = False
        with self._lock:
            for sock in self._clients:
                try:
                    sock.close()
                except OSError:
                    pass
            self._clients.clear()
            self._subscribers.clear()
            self._topic_subs.clear()
        if self._server_sock:
            self._server_sock.close()
        logger.info("TCP server closed")

    def _accept_loop(self) -> None:
        assert self._server_sock is not None  # set by start() before this thread
        while self._running:
            try:
                client, addr = self._server_sock.accept()
                logger.info("Client connected: %s", addr)
                with self._lock:
                    self._clients.append(client)
                threading.Thread(
                    target=self._client_loop, args=(client,), daemon=True
                ).start()
            except TimeoutError:
                continue
            except OSError:
                break

    def _client_loop(self, sock: socket.socket) -> None:
        try:
            while self._running:
                raw = _recv_msg(sock)
                if raw is None:
                    break
                msg = _deserialize(raw)
                self._dispatch(msg)
        except Exception as exc:
            logger.debug("Client handler error: %s", exc)
        finally:
            with self._lock:
                if sock in self._clients:
                    self._clients.remove(sock)
            try:
                sock.close()
            except OSError:
                pass

    def _dispatch(self, msg: Message) -> None:
        topic = msg.topic
        with self._lock:
            for sub_id, callback in list(self._subscribers.items()):
                sub_topic = None
                for t, subs in self._topic_subs.items():
                    if sub_id in subs:
                        sub_topic = t
                        break
                if sub_topic and _topic_matches(topic, sub_topic):
                    try:
                        callback(msg)
                    except Exception as exc:
                        logger.error("Subscriber callback error: %s", exc)
            self._queues[topic].put(msg)

    def send(self, message: Message) -> None:
        data = _serialize(message)
        with self._lock:
            for sock in list(self._clients):
                try:
                    _send_msg(sock, data)
                except Exception:
                    self._clients.remove(sock)

    def receive(self, topic: str, timeout: Optional[float] = None) -> Optional[Message]:
        try:
            return self._queues[topic].get(timeout=timeout)
        except Empty:
            return None

    async def receive_async(
        self, topic: str, timeout: Optional[float] = None
    ) -> Optional[Message]:
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self._queues[topic].get(timeout=1)),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, Empty):
            return None

    def subscribe(self, topic: str, callback: Callable[[Message], None]) -> str:
        sub_id = str(uuid4())
        with self._lock:
            self._subscribers[sub_id] = callback
            self._topic_subs[topic].append(sub_id)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            if subscription_id not in self._subscribers:
                return False
            del self._subscribers[subscription_id]
            for subs in self._topic_subs.values():
                if subscription_id in subs:
                    subs.remove(subscription_id)
                    break
            return True


class TCPClientTransport(Transport):
    """TCP client transport — connects to a TCPServerTransport.

    Usage::

        transport = TCPClientTransport(host="gpu-server", port=9090)
        transport.connect()
        queue = MessageQueue(transport=transport)
        rpc = RPCClient(queue, service_name="torchestrator")
    """

    def __init__(self, host: str = "localhost", port: int = 9090) -> None:
        self._host = host
        self._port = port
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._recv_thread: Optional[threading.Thread] = None
        self._subscribers: Dict[str, Callable[[Message], None]] = {}
        self._topic_subs: Dict[str, List[str]] = defaultdict(list)
        self._queues: Dict[str, Queue[Message]] = defaultdict(Queue)
        self._lock = threading.RLock()

    def connect(self) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.connect((self._host, self._port))
        self._running = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()
        logger.info("Connected to %s:%d", self._host, self._port)

    def close(self) -> None:
        self._running = False
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
        with self._lock:
            self._subscribers.clear()
            self._topic_subs.clear()
        logger.info("TCP client disconnected")

    def _recv_loop(self) -> None:
        try:
            while self._running and self._socket:
                raw = _recv_msg(self._socket)
                if raw is None:
                    break
                msg = _deserialize(raw)
                self._dispatch(msg)
        except Exception as exc:
            if self._running:
                logger.debug("Recv loop error: %s", exc)

    def _dispatch(self, msg: Message) -> None:
        topic = msg.topic
        with self._lock:
            for sub_id, callback in list(self._subscribers.items()):
                sub_topic = None
                for t, subs in self._topic_subs.items():
                    if sub_id in subs:
                        sub_topic = t
                        break
                if sub_topic and _topic_matches(topic, sub_topic):
                    try:
                        callback(msg)
                    except Exception as exc:
                        logger.error("Subscriber callback error: %s", exc)
            self._queues[topic].put(msg)

    def send(self, message: Message) -> None:
        if self._socket is None:
            raise ConnectionError("Not connected — call connect() first")
        _send_msg(self._socket, _serialize(message))

    def receive(self, topic: str, timeout: Optional[float] = None) -> Optional[Message]:
        try:
            return self._queues[topic].get(timeout=timeout)
        except Empty:
            return None

    async def receive_async(
        self, topic: str, timeout: Optional[float] = None
    ) -> Optional[Message]:
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self._queues[topic].get(timeout=1)),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, Empty):
            return None

    def subscribe(self, topic: str, callback: Callable[[Message], None]) -> str:
        sub_id = str(uuid4())
        with self._lock:
            self._subscribers[sub_id] = callback
            self._topic_subs[topic].append(sub_id)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            if subscription_id not in self._subscribers:
                return False
            del self._subscribers[subscription_id]
            for subs in self._topic_subs.values():
                if subscription_id in subs:
                    subs.remove(subscription_id)
                    break
            return True
