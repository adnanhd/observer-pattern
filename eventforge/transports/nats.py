"""NATS transport over core NATS pub/sub.

``nats-py`` is async-only, so this transport runs a private asyncio event loop
in a daemon thread and bridges the synchronous ``Transport`` ABC onto it with
``asyncio.run_coroutine_threadsafe``. JSON on the wire
(``Message.model_dump_json`` / ``Message.model_validate_json``) -- no pickle.

This module is optional: ``import eventforge`` and
``import eventforge.transports`` never require ``nats``. Import it explicitly::

    from eventforge.transports.nats import NatsTransport

and install the extra::

    pip install eventforge[nats]

Wildcard mapping (eventforge topic -> NATS subject). NATS subjects use
``.``-separated tokens with ``*`` (single token) and ``>`` (one-or-more
trailing tokens) wildcards:
    ``**`` -> ``>``   (match the rest of the subject, any number of tokens)
    ``*``  -> ``*``   (match exactly one token)
Other characters pass through unchanged. Delivered messages are still filtered
locally via ``_matches`` (segment-aware, like memory.py) before a subscriber
callback fires.
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from queue import Empty, Queue
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from eventforge.transports.base import Transport
from eventforge.types import Message

if TYPE_CHECKING:
    from nats.aio.client import Client as NatsClient
    from nats.aio.msg import Msg as NatsMsg
    from nats.aio.subscription import Subscription as NatsSubscription


def _to_nats_subject(topic: str) -> str:
    """Map an eventforge topic to a NATS subject (``**`` -> ``>``, ``*`` -> ``*``)."""
    tokens = topic.split(".")
    out: list[str] = []
    for tok in tokens:
        if tok == "**":
            out.append(">")
        else:
            out.append(tok)
    return ".".join(out)


def _matches(topic: str, pattern: str) -> bool:
    """Check if topic matches an eventforge pattern.

    Segment-aware: ``*`` matches a single ``.``-delimited segment, ``**``
    matches any number of segments.
    """
    if pattern == topic:
        return True
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern[i : i + 2] == "**":
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^.]*")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return re.match("^" + "".join(parts) + "$", topic) is not None


class NatsTransport(Transport):
    """Thread-safe NATS pub/sub transport bridged onto a private event loop."""

    def __init__(
        self,
        servers: str | list[str] = "nats://localhost:4222",
        *,
        connect_timeout: float = 2.0,
        **kwargs: Any,
    ) -> None:
        try:
            import nats
        except ImportError as exc:  # pragma: no cover - exercised w/o extra
            raise RuntimeError(
                "NatsTransport requires the 'nats' extra: pip install eventforge[nats]"
            ) from exc

        self._nats = nats
        self._servers = servers
        self._connect_timeout = connect_timeout
        self._connect_kwargs = kwargs
        self._nc: NatsClient | None = None
        self._subscribers: dict[str, Callable[[Message], None]] = {}
        self._sub_topic: dict[str, str] = {}
        self._nats_subs: dict[str, NatsSubscription] = {}
        self._queues: dict[str, Queue[Message]] = defaultdict(Queue)
        self._queue_subs: dict[str, NatsSubscription] = {}
        self._lock = threading.RLock()
        self._callback_pool = ThreadPoolExecutor(max_workers=4)
        self._running = True

        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()
        self._ready.wait()

        # Bound the initial connect so a missing server fails fast (raises)
        # instead of hanging the caller -- e.g. CI / tests with no NATS server.
        # On failure, tear down the loop thread + pool so we don't leak them.
        try:
            self._run(self._connect(), timeout=self._connect_timeout + 2.0)
        except BaseException:
            self._running = False
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._callback_pool.shutdown(wait=False)
            raise

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._ready.set)
        self._loop.run_forever()

    def _run(self, coro: Any, timeout: float | None = None) -> Any:
        """Run a coroutine on the private loop from a sync caller and wait."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            future.cancel()  # don't leave the coroutine pending (noisy warning)
            raise

    async def _connect(self) -> None:
        # allow_reconnect=False + a short connect_timeout so an unreachable
        # server raises promptly rather than retrying with backoff.
        kwargs: dict[str, Any] = {
            "connect_timeout": self._connect_timeout,
            "allow_reconnect": False,
            "max_reconnect_attempts": 0,
            **self._connect_kwargs,
        }
        self._nc = await self._nats.connect(self._servers, **kwargs)

    def _make_cb(self) -> Callable[[NatsMsg], Any]:
        async def _cb(nats_msg: NatsMsg) -> None:
            try:
                msg = Message.model_validate_json(nats_msg.data.decode())
            except Exception:
                return
            self._dispatch(msg)

        return _cb

    def _dispatch(self, msg: Message) -> None:
        topic = msg.topic
        with self._lock:
            for sub_id, callback in list(self._subscribers.items()):
                sub_topic = self._sub_topic.get(sub_id)
                if sub_topic is not None and _matches(topic, sub_topic):
                    # Run sync callbacks off the event loop thread.
                    self._callback_pool.submit(self._safe_call, callback, msg)
            self._queues[topic].put(msg)

    @staticmethod
    def _safe_call(callback: Callable[[Message], None], msg: Message) -> None:
        try:
            callback(msg)
        except Exception:
            pass

    def send(self, message: Message) -> None:
        if not self._running or self._nc is None:
            raise RuntimeError("Transport is closed")
        subject = _to_nats_subject(message.topic)
        data = message.model_dump_json().encode()

        async def _pub() -> None:
            assert self._nc is not None
            await self._nc.publish(subject, data)
            await self._nc.flush()

        self._run(_pub())

    def receive(self, topic: str, timeout: float | None = None) -> Message | None:
        if not self._running:
            return None
        self._ensure_queue_subscription(topic)
        try:
            return self._queues[topic].get(timeout=timeout)
        except Empty:
            return None

    async def receive_async(
        self, topic: str, timeout: float | None = None
    ) -> Message | None:
        if not self._running:
            return None
        self._ensure_queue_subscription(topic)
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self._queues[topic].get(timeout=1)),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, Empty):
            return None

    def _ensure_queue_subscription(self, topic: str) -> None:
        with self._lock:
            if topic in self._queue_subs:
                return
            subject = _to_nats_subject(topic)

            async def _sub() -> NatsSubscription:
                assert self._nc is not None
                return await self._nc.subscribe(subject, cb=self._make_cb())

            self._queue_subs[topic] = self._run(_sub())

    def subscribe(self, topic: str, callback: Callable[[Message], None]) -> str:
        if not self._running or self._nc is None:
            raise RuntimeError("Transport is closed")
        sub_id = uuid4().hex
        subject = _to_nats_subject(topic)

        async def _sub() -> NatsSubscription:
            assert self._nc is not None
            return await self._nc.subscribe(subject, cb=self._make_cb())

        nats_sub = self._run(_sub())
        with self._lock:
            self._subscribers[sub_id] = callback
            self._sub_topic[sub_id] = topic
            self._nats_subs[sub_id] = nats_sub
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            if subscription_id not in self._subscribers:
                return False
            del self._subscribers[subscription_id]
            self._sub_topic.pop(subscription_id, None)
            nats_sub = self._nats_subs.pop(subscription_id, None)
        if nats_sub is not None:
            try:
                self._run(nats_sub.unsubscribe())
            except Exception:
                pass
        return True

    def close(self) -> None:
        if not self._running:
            return
        self._running = False
        nc = self._nc
        if nc is not None:

            async def _drain() -> None:
                try:
                    await nc.drain()
                except Exception:
                    try:
                        await nc.close()
                    except Exception:
                        pass

            try:
                self._run(_drain())
            except Exception:
                pass
        self._nc = None
        with self._lock:
            self._subscribers.clear()
            self._sub_topic.clear()
            self._nats_subs.clear()
            self._queue_subs.clear()
        self._callback_pool.shutdown(wait=False)
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread is not threading.current_thread():
            self._loop_thread.join(timeout=2.0)
