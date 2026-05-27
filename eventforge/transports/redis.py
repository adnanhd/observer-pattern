"""Redis transport over Redis PUBLISH / (P)SUBSCRIBE.

Uses JSON on the wire (``Message.model_dump_json`` /
``Message.model_validate_json``) -- no pickle -- mirroring the TCP transport.

This module is optional: ``import eventforge`` and
``import eventforge.transports`` never require ``redis``. Import it explicitly::

    from eventforge.transports.redis import RedisTransport

and install the extra::

    pip install eventforge[redis]

Wildcard mapping (eventforge topic -> Redis glob pattern used with PSUBSCRIBE):
    ``**`` -> ``*``   (match across any number of ``.`` segments)
    ``*``  -> ``*``   (Redis glob ``*`` is greedy and also crosses ``.``)
Concrete topics with no ``*`` are pattern-subscribed verbatim, which a
PSUBSCRIBE treats as an exact-match pattern. Delivered messages are still
filtered locally via ``_matches`` (segment-aware, like memory.py) before a
subscriber callback fires, so the segment semantics of eventforge ``*`` vs
``**`` are preserved even though the Redis glob is coarser.
"""

from __future__ import annotations

import re
import threading
from collections import defaultdict
from collections.abc import Callable
from queue import Empty, Queue
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from eventforge.transports.base import Transport
from eventforge.types import Message

if TYPE_CHECKING:
    import redis as redis_mod


def _to_redis_pattern(topic: str) -> str:
    """Map an eventforge topic to a Redis glob pattern for PSUBSCRIBE.

    ``**`` and ``*`` both map to a Redis ``*``. Local ``_matches`` then
    enforces the finer segment semantics.
    """
    return topic.replace("**", "*")


def _matches(topic: str, pattern: str) -> bool:
    """Check if topic matches an eventforge pattern.

    Segment-aware (like memory.py's intent): ``*`` matches a single
    ``.``-delimited segment, ``**`` matches any number of segments.
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


class RedisTransport(Transport):
    """Thread-safe Redis pub/sub transport.

    A single background daemon thread runs the pubsub ``get_message`` loop and,
    for every incoming message, (a) invokes each matching subscriber callback
    and (b) buffers the message on a per-topic ``Queue`` so ``receive()`` works.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        *,
        db: int = 0,
        client: Any | None = None,
        **redis_kwargs: Any,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            try:
                import redis
            except ImportError as exc:  # pragma: no cover - exercised w/o extra
                raise RuntimeError(
                    "RedisTransport requires the 'redis' extra: "
                    "pip install eventforge[redis]"
                ) from exc
            self._client = redis.Redis(host=host, port=port, db=db, **redis_kwargs)

        self._pubsub: redis_mod.client.PubSub = self._client.pubsub()
        self._subscribers: dict[str, Callable[[Message], None]] = {}
        self._sub_topic: dict[str, str] = {}
        self._sub_pattern: dict[str, str] = {}
        # Redis glob pattern -> refcount, so we only PUNSUBSCRIBE when the last
        # subscription/receive-queue using a pattern goes away.
        self._pattern_refs: dict[str, int] = defaultdict(int)
        self._queues: dict[str, Queue[Message]] = defaultdict(Queue)
        self._queue_patterns: dict[str, str] = {}
        self._lock = threading.RLock()
        self._running = True
        self._listener = threading.Thread(target=self._listen, daemon=True)
        self._listener.start()

    def _psubscribe(self, pattern: str) -> None:
        """Ensure the listener is pattern-subscribed to ``pattern`` (refcounted)."""
        if self._pattern_refs[pattern] == 0:
            self._pubsub.psubscribe(pattern)
        self._pattern_refs[pattern] += 1

    def _punsubscribe(self, pattern: str) -> None:
        """Drop one ref to ``pattern``; PUNSUBSCRIBE when it hits zero."""
        if self._pattern_refs.get(pattern, 0) == 0:
            return
        self._pattern_refs[pattern] -= 1
        if self._pattern_refs[pattern] == 0:
            del self._pattern_refs[pattern]
            try:
                self._pubsub.punsubscribe(pattern)
            except Exception:
                pass

    def _ensure_queue_subscription(self, topic: str) -> None:
        """Ensure a pattern subscription exists so ``receive(topic)`` works."""
        with self._lock:
            if topic in self._queue_patterns:
                return
            pattern = _to_redis_pattern(topic)
            self._queue_patterns[topic] = pattern
            self._psubscribe(pattern)

    def _listen(self) -> None:
        while self._running:
            try:
                raw = self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.2
                )
            except Exception:
                if not self._running:
                    break
                continue
            if raw is None:
                continue
            if raw.get("type") not in ("message", "pmessage"):
                continue
            data = raw.get("data")
            if isinstance(data, bytes):
                payload = data.decode()
            elif isinstance(data, str):
                payload = data
            else:
                continue
            try:
                msg = Message.model_validate_json(payload)
            except Exception:
                continue
            self._dispatch(msg)

    def _dispatch(self, msg: Message) -> None:
        topic = msg.topic
        with self._lock:
            for sub_id, callback in list(self._subscribers.items()):
                sub_topic = self._sub_topic.get(sub_id)
                if sub_topic is not None and _matches(topic, sub_topic):
                    try:
                        callback(msg)
                    except Exception:
                        pass  # Don't let callback errors break the listener
            self._queues[topic].put(msg)

    def send(self, message: Message) -> None:
        if not self._running:
            raise RuntimeError("Transport is closed")
        self._client.publish(message.topic, message.model_dump_json())

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
        import asyncio

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

    def subscribe(self, topic: str, callback: Callable[[Message], None]) -> str:
        if not self._running:
            raise RuntimeError("Transport is closed")
        sub_id = uuid4().hex
        pattern = _to_redis_pattern(topic)
        with self._lock:
            self._subscribers[sub_id] = callback
            self._sub_topic[sub_id] = topic
            self._sub_pattern[sub_id] = pattern
            self._psubscribe(pattern)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            if subscription_id not in self._subscribers:
                return False
            del self._subscribers[subscription_id]
            self._sub_topic.pop(subscription_id, None)
            pattern = self._sub_pattern.pop(subscription_id, None)
            if pattern is not None:
                self._punsubscribe(pattern)
            return True

    def close(self) -> None:
        self._running = False
        is_self = self._listener is threading.current_thread()
        if self._listener.is_alive() and not is_self:
            self._listener.join(timeout=2.0)
        with self._lock:
            self._subscribers.clear()
            self._sub_topic.clear()
            self._sub_pattern.clear()
            self._pattern_refs.clear()
            self._queue_patterns.clear()
        try:
            self._pubsub.close()
        except Exception:
            pass
        try:
            self._client.close()
        except Exception:
            pass
