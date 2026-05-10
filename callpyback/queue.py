"""Topic-keyed message queue built on Observable + Eventful primitives.

Each topic is a dynamically-created :class:`Eventful` channel held in a
dict. ``publish`` sends through the underlying :class:`Transport` so
cross-process delivery still works; the transport's local callback then
fires the topic's Eventful, which dispatches to subscribers via the
channel's pluggable :class:`Dispatcher`.

Three equivalent ways to subscribe::

    queue.subscribe("foo", handler)         # legacy API
    queue.on("foo", handler)                # Observable string form
    queue.topic("foo").on(handler)          # Eventful direct (autocomplete-safe
                                            # since topic() returns the Eventful)
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from callpyback.observers import BroadcastDispatcher, Dispatcher, Eventful, Observable
from callpyback.transports.base import Transport
from callpyback.transports.memory import MemoryTransport
from callpyback.types import Message

Handler = Callable[[Message], None]
AsyncHandler = Callable[[Message], Any]


__all__ = ["MessageQueue", "Handler", "AsyncHandler"]


class MessageQueue(Observable):
    """Topic-keyed pub-sub backed by a Transport."""

    def __init__(self, transport: Optional[Transport] = None) -> None:
        self._transport = transport or MemoryTransport()
        self._topics: Dict[str, Eventful] = {}
        # handler_id -> (topic, fn), so unsubscribe can find + remove the
        # actual subscriber from the topic's Eventful.
        self._sub_ids: Dict[str, "tuple[str, Handler]"] = {}
        # topic -> transport subscription id (one transport sub per topic).
        self._transport_subs: Dict[str, str] = {}
        self._lock = threading.RLock()

    # ---- topic management ----------------------------------------------

    def topic(
        self,
        name: str,
        dispatcher: Optional[Dispatcher] = None,
    ) -> Eventful:
        """Get-or-create the :class:`Eventful` channel for topic ``name``.

        On first access a transport subscription is registered that
        relays delivered messages into the channel's ``fire``. Pass
        ``dispatcher=`` to install a non-default Dispatcher (e.g.
        ``RoundRobinDispatcher`` for competing-consumer fan-in).
        """
        with self._lock:
            if name in self._topics:
                return self._topics[name]
            channel = Eventful(dispatcher=dispatcher or BroadcastDispatcher())
            self._topics[name] = channel
            # Wire transport -> Eventful so cross-process delivery still
            # fans out to whatever subscribers attach later.
            sub_id = self._transport.subscribe(name, channel.fire)
            self._transport_subs[name] = sub_id
            return channel

    # ---- Observable surface (string-keyed routing) ---------------------

    def on(self, event_or_topic: str, fn: Optional[Handler] = None):
        """Subscribe ``fn`` to ``event_or_topic``. Two forms:

          - ``queue.on("topic", handler)`` -- subscribe directly,
            returns a ``handler_id`` string.
          - ``@queue.on("topic")`` -- decorator form; returns a decorator
            that subscribes the decorated function and returns it
            unchanged (so the function name stays usable in code).
        """
        if fn is None:
            def deco(handler: Handler) -> Handler:
                self.subscribe(event_or_topic, handler)
                return handler
            return deco
        return self.subscribe(event_or_topic, fn)

    def subscribe(self, topic: str, fn: Handler) -> str:
        """Subscribe ``fn`` to ``topic``. Returns a ``handler_id``."""
        channel = self.topic(topic)
        channel.subscribe(fn)
        handler_id = str(uuid4())
        with self._lock:
            self._sub_ids[handler_id] = (topic, fn)
        return handler_id

    def fire(self, event_or_topic: str, *args: Any, **kwargs: Any) -> str:
        """Publish a message to the topic. Goes through the transport so
        cross-process subscribers receive it too. Positional args after
        the topic are the payload; kwargs become message headers."""
        payload = args[0] if args else None
        return self.publish(event_or_topic, payload, **kwargs)

    # ---- publish + async variants -------------------------------------

    def publish(self, topic: str, payload: Any, **headers: Any) -> str:
        """Publish message to topic. Returns message_id."""
        message = Message(topic=topic, payload=payload, headers=headers)
        self._transport.send(message)
        return message.id

    async def publish_async(self, topic: str, payload: Any, **headers: Any) -> str:
        """Publish asynchronously (currently just delegates)."""
        return self.publish(topic, payload, **headers)

    # ---- unsubscribe + decorator + receive ----------------------------

    def unsubscribe(self, handler_id: str) -> bool:
        """Unsubscribe by ``handler_id``. Returns True iff removed."""
        with self._lock:
            entry = self._sub_ids.pop(handler_id, None)
            if entry is None:
                return False
            topic, fn = entry
            channel = self._topics.get(topic)
            if channel is None:
                return False
            return channel.unsubscribe(fn)

    def receive(self, topic: str, timeout: Optional[float] = None) -> Optional[Message]:
        """Receive next message from topic (blocking)."""
        return self._transport.receive(topic, timeout)

    async def receive_async(
        self,
        topic: str,
        timeout: Optional[float] = None,
    ) -> Optional[Message]:
        """Receive next message from topic (async)."""
        return await self._transport.receive_async(topic, timeout)

    # ---- request-reply -------------------------------------------------

    def request(
        self,
        topic: str,
        payload: Any,
        timeout: float = 30.0,
        **headers: Any,
    ) -> Optional[Message]:
        """Send a request and wait for a reply on a unique reply topic."""
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
        self,
        topic: str,
        payload: Any,
        timeout: float = 30.0,
        **headers: Any,
    ) -> Optional[Message]:
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

    def reply(self, original: Message, payload: Any, **headers: Any) -> str:
        """Reply to a message via its ``reply_to`` topic."""
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

    # ---- task helper ---------------------------------------------------

    def register_task(self, topic: str, task_func: Callable) -> str:
        """Subscribe a task function that auto-unpacks the message payload.

        Dict payload -> kwargs; list/tuple -> positional args; otherwise
        passed as a single arg.
        """

        def handler(msg: Message):
            payload = msg.payload
            if isinstance(payload, dict):
                return task_func(**payload)
            if isinstance(payload, (list, tuple)):
                return task_func(*payload)
            return task_func(payload)

        return self.subscribe(topic, handler)

    # ---- shutdown ------------------------------------------------------

    def close(self) -> None:
        """Close the underlying transport."""
        self._transport.close()

    def __enter__(self) -> "MessageQueue":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ---- introspection -------------------------------------------------

    def topics(self) -> List[str]:
        """Names of all topics currently tracked."""
        with self._lock:
            return list(self._topics)
