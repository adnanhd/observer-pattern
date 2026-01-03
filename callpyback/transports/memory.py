"""In-memory transport for single-process messaging."""

import asyncio
import fnmatch
import threading
from collections import defaultdict
from queue import Empty, Queue
from typing import Callable, Dict, List, Optional
from uuid import uuid4

from callpyback.transports.base import Transport
from callpyback.types import Message


class MemoryTransport(Transport):
    """Thread-safe in-memory message transport."""

    def __init__(self, max_queue_size: int = 1000):
        self._queues: Dict[str, Queue] = defaultdict(
            lambda: Queue(maxsize=max_queue_size)
        )
        self._subscribers: Dict[str, Callable[[Message], None]] = {}
        self._topic_subs: Dict[str, List[str]] = defaultdict(list)
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

            # Notify matching subscribers
            for sub_id, callback in list(self._subscribers.items()):
                sub_topic = None
                for t, subs in self._topic_subs.items():
                    if sub_id in subs:
                        sub_topic = t
                        break

                if sub_topic and self._matches(topic, sub_topic):
                    try:
                        callback(message)
                    except Exception:
                        pass  # Don't let callback errors break send

    def receive(self, topic: str, timeout: Optional[float] = None) -> Optional[Message]:
        """Receive next message from topic (blocking)."""
        if self._closed:
            return None

        try:
            return self._queues[topic].get(timeout=timeout)
        except Empty:
            return None

    async def receive_async(
        self, topic: str, timeout: Optional[float] = None
    ) -> Optional[Message]:
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

        sub_id = str(uuid4())
        with self._lock:
            self._subscribers[sub_id] = callback
            self._topic_subs[topic].append(sub_id)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe by ID."""
        with self._lock:
            if subscription_id not in self._subscribers:
                return False

            del self._subscribers[subscription_id]
            for topic, subs in self._topic_subs.items():
                if subscription_id in subs:
                    subs.remove(subscription_id)
                    break
            return True

    def close(self) -> None:
        """Close transport."""
        self._closed = True
        with self._lock:
            self._subscribers.clear()
            self._topic_subs.clear()

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
