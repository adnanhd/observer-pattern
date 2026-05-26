"""Remote message queue subscription and bridging."""

import threading
from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

from eventforge.queue import MessageQueue
from eventforge.rpc import RPCClient, RPCServer
from eventforge.types import Message


class RemoteSubscription:
    """Represents a remote subscription to a topic."""

    def __init__(
        self,
        subscription_id: str,
        topic: str,
        remote_service: str,
        handler: Callable[[Message], Any],
    ):
        self.subscription_id = subscription_id
        self.topic = topic
        self.remote_service = remote_service
        self.handler = handler


class RemoteQueue:
    """Message queue with remote subscription support.

    Bridges local and remote message queues, allowing:
    - Subscribe to topics on remote services
    - Publish messages that reach remote subscribers
    - Forward messages between local and remote queues

    Example:
        # Local node
        local_queue = MessageQueue()
        remote = RemoteQueue(local_queue, node_id="node-1")

        # Connect to remote node
        remote.connect("node-2", remote_queue_instance)

        # Subscribe to remote topic
        @remote.subscribe_remote("node-2", "events.user")
        def handle_user_event(msg):
            print(f"Received from node-2: {msg.payload}")

        # Publish to remote
        remote.publish_remote("node-2", "events.order", {"id": 123})
    """

    def __init__(
        self,
        queue: MessageQueue,
        node_id: str | None = None,
    ):
        self._queue = queue
        self._node_id = node_id or str(uuid4())[:8]
        self._remote_connections: dict[str, MessageQueue] = {}
        self._rpc_servers: dict[str, RPCServer] = {}
        self._rpc_clients: dict[str, RPCClient] = {}
        self._remote_subscriptions: dict[str, RemoteSubscription] = {}
        self._lock = threading.RLock()

        # Setup local RPC server for remote subscriptions
        self._setup_rpc_server()

    def _setup_rpc_server(self) -> None:
        """Setup RPC server for handling remote subscription requests."""
        self._local_server = RPCServer(
            self._queue,
            service_name=f"remote.{self._node_id}",
        )

        @self._local_server.register(name="subscribe")
        def handle_subscribe(topic: str, reply_topic: str) -> str:
            """Handle remote subscription request."""
            sub_id = str(uuid4())

            def forward_handler(msg: Message) -> None:
                # Forward message to remote subscriber
                self._queue.publish(reply_topic, msg.model_dump())

            self._queue.subscribe(topic, forward_handler)
            return sub_id

        @self._local_server.register(name="publish")
        def handle_publish(topic: str, payload: Any, headers: dict[str, Any]) -> str:
            """Handle remote publish request."""
            return self._queue.publish(topic, payload, **headers)

        self._local_server.serve(blocking=False)

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def local_queue(self) -> MessageQueue:
        return self._queue

    def connect(self, remote_node_id: str, remote_queue: MessageQueue) -> None:
        """Connect to a remote node's queue.

        Args:
            remote_node_id: Identifier for the remote node
            remote_queue: The remote node's MessageQueue instance
        """
        with self._lock:
            self._remote_connections[remote_node_id] = remote_queue
            self._rpc_clients[remote_node_id] = RPCClient(
                remote_queue,
                service_name=f"remote.{remote_node_id}",
                timeout=30.0,
            )

    def disconnect(self, remote_node_id: str) -> bool:
        """Disconnect from a remote node."""
        with self._lock:
            if remote_node_id in self._remote_connections:
                del self._remote_connections[remote_node_id]
                del self._rpc_clients[remote_node_id]
                return True
            return False

    def subscribe_remote(
        self,
        remote_node_id: str,
        topic: str,
    ) -> Callable[[Callable[[Message], Any]], Callable[[Message], Any]]:
        """Decorator to subscribe to a topic on a remote node.

        Args:
            remote_node_id: The remote node to subscribe to
            topic: Topic pattern to subscribe to

        Example:
            @remote.subscribe_remote("node-2", "events.*")
            def handler(msg):
                print(msg.payload)
        """

        def decorator(handler: Callable[[Message], Any]) -> Callable[[Message], Any]:
            self.add_remote_subscription(remote_node_id, topic, handler)
            return handler

        return decorator

    def add_remote_subscription(
        self,
        remote_node_id: str,
        topic: str,
        handler: Callable[[Message], Any],
    ) -> str:
        """Subscribe to a topic on a remote node.

        Args:
            remote_node_id: The remote node to subscribe to
            topic: Topic pattern to subscribe to
            handler: Callback for received messages

        Returns:
            Subscription ID
        """
        with self._lock:
            client = self._rpc_clients.get(remote_node_id)
            if not client:
                raise ValueError(f"Not connected to remote node: {remote_node_id}")

            # Create a reply topic for forwarded messages
            reply_topic = f"_remote_sub.{self._node_id}.{uuid4()}"

            # Subscribe locally to receive forwarded messages
            def local_handler(msg: Message) -> None:
                try:
                    # Reconstruct the original message
                    if isinstance(msg.payload, dict) and "topic" in msg.payload:
                        original = Message.model_validate(msg.payload)
                        handler(original)
                    else:
                        handler(msg)
                except Exception:
                    pass

            self._queue.subscribe(reply_topic, local_handler)

            # Request remote subscription; the remote "subscribe" handler
            # returns a subscription-id string.
            sub_id = cast(str, client.call("subscribe", topic, reply_topic))

            subscription = RemoteSubscription(
                subscription_id=sub_id,
                topic=topic,
                remote_service=remote_node_id,
                handler=handler,
            )
            self._remote_subscriptions[sub_id] = subscription

            return sub_id

    def publish_remote(
        self,
        remote_node_id: str,
        topic: str,
        payload: Any,
        **headers: Any,
    ) -> str:
        """Publish a message to a remote node.

        Args:
            remote_node_id: The remote node to publish to
            topic: Topic to publish to
            payload: Message payload
            **headers: Additional headers

        Returns:
            Message ID from remote
        """
        with self._lock:
            client = self._rpc_clients.get(remote_node_id)
            if not client:
                raise ValueError(f"Not connected to remote node: {remote_node_id}")

            # The remote "publish" handler returns a message-id string.
            return cast(str, client.call("publish", topic, payload, headers))

    def publish(self, topic: str, payload: Any, **headers: Any) -> str:
        """Publish to local queue."""
        return self._queue.publish(topic, payload, **headers)

    def subscribe(self, topic: str, handler: Callable[[Message], Any]) -> str:
        """Subscribe to local queue."""
        return self._queue.subscribe(topic, handler)

    def on(
        self, topic: str
    ) -> Callable[[Callable[[Message], None]], Callable[[Message], None]]:
        """Decorator for local subscription."""
        return self._queue.on(topic)

    def broadcast(self, topic: str, payload: Any, **headers: Any) -> dict[str, str]:
        """Broadcast message to all connected nodes.

        Returns:
            Dict mapping node_id to message_id
        """
        results = {}

        # Publish locally
        results[self._node_id] = self._queue.publish(topic, payload, **headers)

        # Publish to all remotes
        with self._lock:
            for node_id, client in self._rpc_clients.items():
                try:
                    results[node_id] = client.call("publish", topic, payload, headers)
                except Exception:
                    results[node_id] = ""

        return results

    def close(self) -> None:
        """Close all connections."""
        self._local_server.stop()
        self._queue.close()

    def __enter__(self) -> "RemoteQueue":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
