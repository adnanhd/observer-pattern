"""In-memory transport for single-process messaging."""

import asyncio
import fnmatch
import threading
from collections import defaultdict
from collections.abc import Callable
from queue import Empty, Queue
from uuid import uuid4

from eventforge.transports.base import Transport
from eventforge.types import Message


class MemoryTransport(Transport):
    """Thread-safe in-memory message transport."""

    def __init__(self, max_queue_size: int = 1000):
        self._queues: dict[str, Queue] = defaultdict(
            lambda: Queue(maxsize=max_queue_size)
        )
        self._subscribers: dict[str, Callable[[Message], None]] = {}
        self._topic_subs: dict[str, list[str]] = defaultdict(list)
        # Reverse index: sub_id -> topic pattern. Built at subscribe time so
        # send() can route in O(N_subscribers) rather than scanning every
        # (sub, topic) pair (the previous O(N_subs * N_topics) walk was the
        # dominant cost in MessageQueue.publish per the profiler).
        self._sub_topic: dict[str, str] = {}
        self._lock = threading.RLock()
        self._closed = False

    def send(self, message: Message) -> None:
        """Send message to topic and notify subscribers."""
        if self._closed:
            raise RuntimeError("Transport is closed")

        with self._lock:
            # Add to queue
            topic = message.topic
            try:
                self._queues[topic].put_nowait(message)
            except Exception:
                pass  # Queue full, drop oldest would be better

            # Notify matching subscribers. ``self._sub_topic[sub_id]`` gives
            # the subscription's pattern in O(1); we only run the
            # (potentially expensive) ``_matches`` check after that lookup.
            for sub_id, callback in list(self._subscribers.items()):
                sub_topic = self._sub_topic.get(sub_id)
                if sub_topic is not None and self._matches(topic, sub_topic):
                    try:
                        callback(message)
                    except Exception:
                        pass  # Don't let callback errors break send

    def receive(self, topic: str, timeout: float | None = None) -> Message | None:
        """Receive next message from topic (blocking)."""
        if self._closed:
            return None

        try:
            return self._queues[topic].get(timeout=timeout)
        except Empty:
            return None

    async def receive_async(
        self, topic: str, timeout: float | None = None
    ) -> Message | None:
        """Receive next message from topic (async)."""
        if self._closed:
            return None

        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self._queues[topic].get(timeout=1)),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, Empty):
            return None

    def subscribe(self, topic: str, callback: Callable[[Message], None]) -> str:
        """Subscribe to topic pattern. Returns subscription_id."""
        if self._closed:
            raise RuntimeError("Transport is closed")

        sub_id = uuid4().hex
        with self._lock:
            self._subscribers[sub_id] = callback
            self._topic_subs[topic].append(sub_id)
            self._sub_topic[sub_id] = topic
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe by ID."""
        with self._lock:
            if subscription_id not in self._subscribers:
                return False

            del self._subscribers[subscription_id]
            topic = self._sub_topic.pop(subscription_id, None)
            if topic is not None:
                subs = self._topic_subs.get(topic)
                if subs and subscription_id in subs:
                    subs.remove(subscription_id)
            return True

    def close(self) -> None:
        """Close transport."""
        self._closed = True
        with self._lock:
            self._subscribers.clear()
            self._topic_subs.clear()
            self._sub_topic.clear()

    def _matches(self, topic: str, pattern: str) -> bool:
        """Check if topic matches pattern (supports * and **)."""
        if pattern == topic:
            return True
        # Convert pattern to fnmatch style
        # ** matches any number of segments
        # * matches single segment
        pattern = pattern.replace("**", "__DOUBLE__")
        pattern = pattern.replace("*", "[^.]*")
        pattern = pattern.replace("__DOUBLE__", "*")
        return fnmatch.fnmatch(topic, pattern)
