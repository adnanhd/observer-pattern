"""
Inter-Process Communication (IPC) plugin for CallPyBack.
Provides communication between CallPyBack instances across processes.
"""

import json
import multiprocessing as mp
import pickle
import socket
import struct
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

try:
    import zmq

    HAS_ZMQ = True
except ImportError:
    HAS_ZMQ = False

try:
    import redis

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

from callpyback import CallPyBack
from callpyback.plugins.core.message_queue import Message, MessageQueue


@dataclass
class IPCMessage:
    """IPC message container."""

    id: str
    source_process: str
    target_process: Optional[str]
    message_type: str  # 'pub', 'sub', 'request', 'response', 'control'
    topic: str
    payload: Any
    headers: Dict[str, Any]
    timestamp: float
    reply_to: Optional[str] = None
    correlation_id: Optional[str] = None


class IPCTransport:
    """Base class for IPC transport mechanisms."""

    def __init__(self, process_id: str):
        self.process_id = process_id
        self.running = False

    def start(self):
        """Start transport."""
        self.running = True

    def stop(self):
        """Stop transport."""
        self.running = False

    def send(self, message: IPCMessage):
        """Send message."""
        raise NotImplementedError

    def receive(self, timeout: Optional[float] = None) -> Optional[IPCMessage]:
        """Receive message."""
        raise NotImplementedError

    def broadcast(self, message: IPCMessage):
        """Broadcast message to all processes."""
        raise NotImplementedError


class SocketTransport(IPCTransport):
    """Socket-based IPC transport."""

    def __init__(self, process_id: str, port: int = 0, host: str = "localhost"):
        super().__init__(process_id)
        self.host = host
        self.port = port
        self.socket = None
        self.server_socket = None
        self.connections: Dict[str, socket.socket] = {}
        self.lock = threading.RLock()

        # Process registry for discovery
        self.process_registry: Dict[str, tuple] = {}  # process_id -> (host, port)

    def start(self):
        """Start socket server."""
        super().start()

        # Create server socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))

        # Get actual port if auto-assigned
        self.port = self.server_socket.getsockname()[1]

        self.server_socket.listen(5)

        # Start server thread
        self.server_thread = threading.Thread(
            target=self._server_loop,
            name=f"SocketServer-{self.process_id}",
            daemon=True,
        )
        self.server_thread.start()

    def stop(self):
        """Stop socket server."""
        super().stop()

        if self.server_socket:
            self.server_socket.close()

        with self.lock:
            for conn in self.connections.values():
                conn.close()
            self.connections.clear()

    def register_process(self, process_id: str, host: str, port: int):
        """Register another process for communication."""
        self.process_registry[process_id] = (host, port)

    def send(self, message: IPCMessage):
        """Send message to specific process."""
        target_process = message.target_process
        if not target_process or target_process not in self.process_registry:
            return False

        try:
            # Get or create connection
            connection = self._get_connection(target_process)
            if connection:
                self._send_message(connection, message)
                return True
        except Exception as e:
            print(f"Socket send error: {e}")

        return False

    def broadcast(self, message: IPCMessage):
        """Broadcast message to all registered processes."""
        for process_id in self.process_registry:
            if process_id != self.process_id:
                message.target_process = process_id
                self.send(message)

    def _get_connection(self, process_id: str) -> Optional[socket.socket]:
        """Get or create connection to process."""
        with self.lock:
            if process_id in self.connections:
                return self.connections[process_id]

        if process_id not in self.process_registry:
            return None

        try:
            host, port = self.process_registry[process_id]
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.connect((host, port))

            with self.lock:
                self.connections[process_id] = conn

            return conn
        except Exception:
            return None

    def _send_message(self, connection: socket.socket, message: IPCMessage):
        """Send message over socket connection."""
        data = pickle.dumps(message)
        # Send length first, then data
        connection.sendall(struct.pack("!I", len(data)))
        connection.sendall(data)

    def _receive_message(self, connection: socket.socket) -> Optional[IPCMessage]:
        """Receive message from socket connection."""
        try:
            # Receive length
            length_data = connection.recv(4)
            if not length_data:
                return None

            length = struct.unpack("!I", length_data)[0]

            # Receive message data
            data = b""
            while len(data) < length:
                chunk = connection.recv(length - len(data))
                if not chunk:
                    return None
                data += chunk

            return pickle.loads(data)
        except Exception:
            return None

    def _server_loop(self):
        """Server loop for accepting connections."""
        while self.running:
            try:
                client_socket, address = self.server_socket.accept()

                # Handle client in separate thread
                client_thread = threading.Thread(
                    target=self._handle_client, args=(client_socket,), daemon=True
                )
                client_thread.start()

            except Exception as e:
                if self.running:
                    print(f"Socket server error: {e}")
                    time.sleep(0.1)

    def _handle_client(self, client_socket: socket.socket):
        """Handle client connection."""
        try:
            while self.running:
                message = self._receive_message(client_socket)
                if not message:
                    break

                # Process received message
                self._process_received_message(message)

        except Exception as e:
            print(f"Client handler error: {e}")

        finally:
            client_socket.close()

    def _process_received_message(self, message: IPCMessage):
        """Process received IPC message."""
        # This will be overridden by the IPC manager
        pass


class ZMQTransport(IPCTransport):
    """ZeroMQ-based IPC transport."""

    def __init__(self, process_id: str, base_port: int = 5555):
        if not HAS_ZMQ:
            raise ImportError("ZeroMQ is required. Install with: pip install pyzmq")

        super().__init__(process_id)
        self.base_port = base_port
        self.context = zmq.Context()
        self.publisher = None
        self.subscriber = None
        self.request_socket = None
        self.response_socket = None

    def start(self):
        """Start ZMQ sockets."""
        super().start()

        # Publisher socket
        self.publisher = self.context.socket(zmq.PUB)
        self.publisher.bind(f"tcp://*:{self.base_port}")

        # Subscriber socket
        self.subscriber = self.context.socket(zmq.SUB)
        self.subscriber.setsockopt(zmq.SUBSCRIBE, b"")  # Subscribe to all messages

        # Request-Response sockets
        self.request_socket = self.context.socket(zmq.REQ)
        self.response_socket = self.context.socket(zmq.REP)
        self.response_socket.bind(f"tcp://*:{self.base_port + 1}")

    def stop(self):
        """Stop ZMQ sockets."""
        super().stop()

        if self.publisher:
            self.publisher.close()
        if self.subscriber:
            self.subscriber.close()
        if self.request_socket:
            self.request_socket.close()
        if self.response_socket:
            self.response_socket.close()

        self.context.term()

    def connect_to_peer(self, peer_host: str, peer_port: int):
        """Connect to peer process."""
        if self.subscriber:
            self.subscriber.connect(f"tcp://{peer_host}:{peer_port}")

    def send(self, message: IPCMessage):
        """Send message via ZMQ."""
        try:
            data = pickle.dumps(message)

            if message.message_type in ["pub", "control"]:
                # Use publisher
                self.publisher.send_multipart([message.topic.encode(), data])
            else:
                # Use request socket for request-response
                if self.request_socket:
                    self.request_socket.send(data)
        except Exception as e:
            print(f"ZMQ send error: {e}")

    def receive(self, timeout: Optional[float] = None) -> Optional[IPCMessage]:
        """Receive message via ZMQ."""
        try:
            if self.subscriber:
                if timeout:
                    # Set receive timeout
                    self.subscriber.setsockopt(zmq.RCVTIMEO, int(timeout * 1000))

                topic, data = self.subscriber.recv_multipart()
                return pickle.loads(data)
        except zmq.Again:
            # Timeout
            return None
        except Exception as e:
            print(f"ZMQ receive error: {e}")
            return None

    def broadcast(self, message: IPCMessage):
        """Broadcast via publisher."""
        self.send(message)


class RedisTransport(IPCTransport):
    """Redis-based IPC transport."""

    def __init__(self, process_id: str, redis_url: str = "redis://localhost:6379"):
        if not HAS_REDIS:
            raise ImportError("Redis is required. Install with: pip install redis")

        super().__init__(process_id)
        self.redis_url = redis_url
        self.redis_client = None
        self.pubsub = None
        self.subscriber_thread = None
        self.message_queue = mp.Queue()

    def start(self):
        """Start Redis connection."""
        super().start()

        self.redis_client = redis.from_url(self.redis_url)
        self.pubsub = self.redis_client.pubsub()

        # Subscribe to process-specific channel
        channel = f"callpyback:{self.process_id}"
        self.pubsub.subscribe(channel)

        # Start subscriber thread
        self.subscriber_thread = threading.Thread(
            target=self._subscriber_loop, daemon=True
        )
        self.subscriber_thread.start()

    def stop(self):
        """Stop Redis connection."""
        super().stop()

        if self.pubsub:
            self.pubsub.close()
        if self.redis_client:
            self.redis_client.close()

    def send(self, message: IPCMessage):
        """Send message via Redis."""
        try:
            data = pickle.dumps(message)

            if message.target_process:
                # Send to specific process
                channel = f"callpyback:{message.target_process}"
            else:
                # Broadcast
                channel = "callpyback:broadcast"

            self.redis_client.publish(channel, data)
        except Exception as e:
            print(f"Redis send error: {e}")

    def receive(self, timeout: Optional[float] = None) -> Optional[IPCMessage]:
        """Receive message from queue."""
        try:
            if timeout:
                return self.message_queue.get(timeout=timeout)
            else:
                return self.message_queue.get_nowait()
        except:
            return None

    def broadcast(self, message: IPCMessage):
        """Broadcast via Redis."""
        message.target_process = None
        self.send(message)

    def _subscriber_loop(self):
        """Redis subscriber loop."""
        try:
            for message in self.pubsub.listen():
                if not self.running:
                    break

                if message["type"] == "message":
                    try:
                        ipc_message = pickle.loads(message["data"])
                        self.message_queue.put(ipc_message)
                    except Exception as e:
                        print(f"Redis message decode error: {e}")
        except Exception as e:
            print(f"Redis subscriber error: {e}")


class IPCManager:
    """
    Inter-Process Communication manager for CallPyBack.

    Manages communication between CallPyBack instances across processes
    using various transport mechanisms.
    """

    def __init__(
        self,
        process_id: Optional[str] = None,
        transport_type: str = "socket",
        **transport_kwargs,
    ):
        """
        Initialize IPC manager.

        Args:
            process_id: Unique process identifier
            transport_type: Transport type ('socket', 'zmq', 'redis')
            **transport_kwargs: Transport-specific arguments
        """
        self.process_id = process_id or f"process_{uuid4()}"
        self.transport_type = transport_type

        # Create transport
        if transport_type == "socket":
            self.transport = SocketTransport(self.process_id, **transport_kwargs)
        elif transport_type == "zmq":
            self.transport = ZMQTransport(self.process_id, **transport_kwargs)
        elif transport_type == "redis":
            self.transport = RedisTransport(self.process_id, **transport_kwargs)
        else:
            raise ValueError(f"Unsupported transport type: {transport_type}")

        # Message handlers
        self.message_handlers: Dict[str, Callable] = {}
        self.topic_handlers: Dict[str, List[Callable]] = {}

        # Local message queue integration
        self.local_message_queue: Optional[MessageQueue] = None

        # Request-response tracking
        self.pending_requests: Dict[str, threading.Event] = {}
        self.request_responses: Dict[str, Any] = {}

        # Statistics
        self.stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "broadcasts_sent": 0,
            "requests_sent": 0,
            "responses_sent": 0,
        }

        # Setup transport message handler
        if hasattr(self.transport, "_process_received_message"):
            self.transport._process_received_message = self._handle_received_message

        # Receiver thread
        self.receiver_thread = None
        self.running = False

    def start(self):
        """Start IPC manager."""
        self.running = True
        self.transport.start()

        # Start receiver thread for non-callback transports
        if self.transport_type in ["socket", "zmq"]:
            self.receiver_thread = threading.Thread(
                target=self._receiver_loop,
                name=f"IPC-Receiver-{self.process_id}",
                daemon=True,
            )
            self.receiver_thread.start()

    def stop(self):
        """Stop IPC manager."""
        self.running = False
        self.transport.stop()

        if self.receiver_thread and self.receiver_thread.is_alive():
            self.receiver_thread.join(timeout=5.0)

    def connect_to_message_queue(self, message_queue: MessageQueue):
        """Connect to local message queue for seamless integration."""
        self.local_message_queue = message_queue

        # Subscribe to all local topics for forwarding
        def forward_to_ipc(message: Message):
            self.publish_remote(message.topic, message.payload, message.headers)

        # This would require modifying MessageQueue to support global observers
        # For now, we'll provide manual integration methods

    def register_process(self, process_id: str, **connection_info):
        """Register another process for communication."""
        if isinstance(self.transport, SocketTransport):
            host = connection_info.get("host", "localhost")
            port = connection_info.get("port")
            if port:
                self.transport.register_process(process_id, host, port)
        elif isinstance(self.transport, ZMQTransport):
            host = connection_info.get("host", "localhost")
            port = connection_info.get("port")
            if host and port:
                self.transport.connect_to_peer(host, port)

    def publish_remote(
        self,
        topic: str,
        payload: Any,
        headers: Optional[Dict[str, Any]] = None,
        target_process: Optional[str] = None,
    ):
        """Publish message to remote processes."""
        message = IPCMessage(
            id=str(uuid4()),
            source_process=self.process_id,
            target_process=target_process,
            message_type="pub",
            topic=topic,
            payload=payload,
            headers=headers or {},
            timestamp=time.time(),
        )

        if target_process:
            self.transport.send(message)
        else:
            self.transport.broadcast(message)

        self.stats["messages_sent"] += 1
        if not target_process:
            self.stats["broadcasts_sent"] += 1

    def subscribe_remote(self, topic: str, handler: Callable):
        """Subscribe to remote topic."""
        if topic not in self.topic_handlers:
            self.topic_handlers[topic] = []
        self.topic_handlers[topic].append(handler)

    def request_remote(
        self, target_process: str, topic: str, payload: Any, timeout: float = 10.0
    ) -> Any:
        """Send request to remote process and wait for response."""
        correlation_id = str(uuid4())

        message = IPCMessage(
            id=str(uuid4()),
            source_process=self.process_id,
            target_process=target_process,
            message_type="request",
            topic=topic,
            payload=payload,
            headers={},
            timestamp=time.time(),
            correlation_id=correlation_id,
        )

        # Setup response tracking
        response_event = threading.Event()
        self.pending_requests[correlation_id] = response_event

        try:
            # Send request
            self.transport.send(message)
            self.stats["requests_sent"] += 1

            # Wait for response
            if response_event.wait(timeout):
                return self.request_responses.pop(correlation_id, None)
            else:
                raise TimeoutError(f"Request timeout after {timeout}s")

        finally:
            # Cleanup
            self.pending_requests.pop(correlation_id, None)
            self.request_responses.pop(correlation_id, None)

    def _receiver_loop(self):
        """Receiver loop for processing messages."""
        while self.running:
            try:
                message = self.transport.receive(timeout=1.0)
                if message:
                    self._handle_received_message(message)
            except Exception as e:
                print(f"IPC receiver error: {e}")
                time.sleep(0.1)

    def _handle_received_message(self, message: IPCMessage):
        """Handle received IPC message."""
        try:
            self.stats["messages_received"] += 1

            if message.message_type == "pub":
                # Handle publication
                self._handle_publication(message)

            elif message.message_type == "request":
                # Handle request
                self._handle_request(message)

            elif message.message_type == "response":
                # Handle response
                self._handle_response(message)

            elif message.message_type == "control":
                # Handle control message
                self._handle_control(message)

        except Exception as e:
            print(f"Message handling error: {e}")

    def _handle_publication(self, message: IPCMessage):
        """Handle published message."""
        topic = message.topic

        # Call topic handlers
        if topic in self.topic_handlers:
            for handler in self.topic_handlers[topic]:
                try:
                    handler(message)
                except Exception as e:
                    print(f"Topic handler error: {e}")

        # Forward to local message queue if connected
        if self.local_message_queue:
            self.local_message_queue.publish(
                topic=topic,
                payload=message.payload,
                headers=message.headers,
                sender=message.source_process,
            )

    def _handle_request(self, message: IPCMessage):
        """Handle request message."""
        # This would need to be implemented based on specific request handling logic
        # For now, just acknowledge
        response_message = IPCMessage(
            id=str(uuid4()),
            source_process=self.process_id,
            target_process=message.source_process,
            message_type="response",
            topic=message.topic,
            payload={"status": "received"},
            headers={},
            timestamp=time.time(),
            correlation_id=message.correlation_id,
        )

        self.transport.send(response_message)
        self.stats["responses_sent"] += 1

    def _handle_response(self, message: IPCMessage):
        """Handle response message."""
        correlation_id = message.correlation_id
        if correlation_id in self.pending_requests:
            self.request_responses[correlation_id] = message.payload
            self.pending_requests[correlation_id].set()

    def _handle_control(self, message: IPCMessage):
        """Handle control message."""
        # Implement control message handling (ping, discovery, etc.)
        pass

    def get_stats(self) -> Dict[str, Any]:
        """Get IPC statistics."""
        return {
            **self.stats,
            "process_id": self.process_id,
            "transport_type": self.transport_type,
            "running": self.running,
            "topic_handlers": len(self.topic_handlers),
            "pending_requests": len(self.pending_requests),
        }

    def discover_processes(self) -> List[str]:
        """Discover other CallPyBack processes."""
        # Send discovery message
        discovery_message = IPCMessage(
            id=str(uuid4()),
            source_process=self.process_id,
            target_process=None,
            message_type="control",
            topic="discovery",
            payload={"action": "ping"},
            headers={},
            timestamp=time.time(),
        )

        self.transport.broadcast(discovery_message)

        # This would need to collect responses
        # For now, return empty list
        return []


# Factory function for easy IPC setup
def create_ipc_cluster(process_configs: List[Dict[str, Any]]) -> List[IPCManager]:
    """
    Create a cluster of IPC-enabled processes.

    Args:
        process_configs: List of process configurations

    Returns:
        List of IPCManager instances
    """
    managers = []

    for config in process_configs:
        manager = IPCManager(**config)
        managers.append(manager)

    # Connect all managers to each other
    for i, manager1 in enumerate(managers):
        for j, manager2 in enumerate(managers):
            if i != j:
                # This would need transport-specific connection logic
                pass

    return managers
