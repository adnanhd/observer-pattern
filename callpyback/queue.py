"""Thread-safe message queue with Pydantic validation."""

import asyncio
import threading
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from callpyback.transports.base import Transport
from callpyback.transports.memory import MemoryTransport
from callpyback.types import Message

Handler = Callable[[Message], None]
AsyncHandler = Callable[[Message], Any]


class MessageQueue:
    """Pub-sub message queue with type validation."""

    def __init__(self, transport: Optional[Transport] = None):
        self._transport = transport or MemoryTransport()
        self._handlers: Dict[str, List[Handler]] = {}
        self._async_handlers: Dict[str, List[AsyncHandler]] = {}
        self._subscriptions: Dict[str, str] = {}  # handler_id -> subscription_id
        self._lock = threading.RLock()

    def publish(self, topic: str, payload: Any, **headers) -> str:
        """Publish message to topic. Returns message_id."""
        message = Message(topic=topic, payload=payload, headers=headers)
        self._transport.send(message)
        return message.id

    async def publish_async(self, topic: str, payload: Any, **headers) -> str:
        """Publish message asynchronously."""
        return self.publish(topic, payload, **headers)

    def subscribe(self, topic: str, handler: Handler) -> str:
        """Subscribe handler to topic. Returns handler_id."""
        handler_id = str(uuid4())

        with self._lock:
            if topic not in self._handlers:
                self._handlers[topic] = []
            self._handlers[topic].append(handler)

            # Register with transport
            def callback(msg: Message):
                for h in self._handlers.get(topic, []):
                    try:
                        h(msg)
                    except Exception:
                        pass

            sub_id = self._transport.subscribe(topic, callback)
            self._subscriptions[handler_id] = sub_id

        return handler_id

    def unsubscribe(self, handler_id: str) -> bool:
        """Unsubscribe handler."""
        with self._lock:
            sub_id = self._subscriptions.pop(handler_id, None)
            if sub_id:
                return self._transport.unsubscribe(sub_id)
            return False

    def on(self, topic: str) -> Callable[[Handler], Handler]:
        """Decorator to subscribe handler to topic."""

        def decorator(handler: Handler) -> Handler:
            self.subscribe(topic, handler)
            return handler

        return decorator

    def receive(self, topic: str, timeout: Optional[float] = None) -> Optional[Message]:
        """Receive next message from topic (blocking)."""
        return self._transport.receive(topic, timeout)

    async def receive_async(
        self, topic: str, timeout: Optional[float] = None
    ) -> Optional[Message]:
        """Receive next message from topic (async)."""
        return await self._transport.receive_async(topic, timeout)

    def request(
        self, topic: str, payload: Any, timeout: float = 30.0, **headers
    ) -> Optional[Message]:
        """Send request and wait for response (request-reply pattern)."""
        reply_topic = f"_reply.{uuid4()}"
        correlation_id = str(uuid4())

        message = Message(
            topic=topic,
            payload=payload,
            headers=headers,
            reply_to=reply_topic,
            correlation_id=correlation_id,
        )

        self._transport.send(message)
        return self._transport.receive(reply_topic, timeout=timeout)

    async def request_async(
        self, topic: str, payload: Any, timeout: float = 30.0, **headers
    ) -> Optional[Message]:
        """Async request-reply."""
        reply_topic = f"_reply.{uuid4()}"
        correlation_id = str(uuid4())

        message = Message(
            topic=topic,
            payload=payload,
            headers=headers,
            reply_to=reply_topic,
            correlation_id=correlation_id,
        )

        self._transport.send(message)
        return await self._transport.receive_async(reply_topic, timeout=timeout)

    def reply(self, original: Message, payload: Any, **headers) -> str:
        """Reply to a message."""
        if not original.reply_to:
            raise ValueError("Original message has no reply_to")

        reply = Message(
            topic=original.reply_to,
            payload=payload,
            headers=headers,
            correlation_id=original.correlation_id,
        )
        self._transport.send(reply)
        return reply.id

    def close(self) -> None:
        """Close queue and transport."""
        self._transport.close()

    def __enter__(self) -> "MessageQueue":
        return self

    def __exit__(self, *args) -> None:
        self.close()
