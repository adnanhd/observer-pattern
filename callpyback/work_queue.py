"""Work queue with competing consumers, ack/nack, and dead-letter support."""

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from callpyback.queue import MessageQueue
from callpyback.transports.base import Transport
from callpyback.types import Message


class QueueFullError(Exception):
    """Raised when enqueue is called on a full work queue."""

    pass


@dataclass
class InFlightEntry:
    """Tracks a message that has been delivered but not yet ack'd."""

    message: Message
    delivery_id: str
    topic: str
    consumer_group: str
    delivered_at: float
    visibility_timeout: float
    retry_count: int


class WorkQueue(MessageQueue):
    """Message queue with competing-consumer semantics.

    Extends MessageQueue with:
    - Competing consumers: round-robin dispatch to one consumer per message
    - Ack/Nack: explicit acknowledgment with requeue or dead-letter
    - Visibility timeout: auto-nack if consumer doesn't ack in time
    - Dead-letter: messages exceeding max retries go to {topic}.dead_letter
    - Backpressure: enqueue raises QueueFullError when queue is full

    The parent publish/subscribe/receive methods continue to work as
    standard pub/sub. The new enqueue/consume/dequeue methods provide
    the competing-consumer pattern alongside.

    Args:
        transport: Optional Transport instance (default MemoryTransport)
        max_work_queue_size: Max pending messages per topic (0 = unlimited)
        default_visibility_timeout: Seconds before unack'd message is redelivered
        max_retries: Max delivery attempts before dead-lettering
        reaper_interval: Seconds between visibility timeout sweeps
    """

    def __init__(
        self,
        transport: Optional[Transport] = None,
        max_work_queue_size: int = 0,
        default_visibility_timeout: float = 30.0,
        max_retries: int = 3,
        reaper_interval: float = 1.0,
    ):
        super().__init__(transport=transport)
        self._max_work_queue_size = max_work_queue_size
        self._default_visibility_timeout = default_visibility_timeout
        self._max_retries = max_retries
        self._reaper_interval = reaper_interval

        self._wq_lock = threading.RLock()
        self._pending: Dict[str, deque] = defaultdict(deque)
        self._in_flight: Dict[str, InFlightEntry] = {}
        self._consumer_groups: Dict[Tuple[str, str], List[Callable]] = defaultdict(
            list
        )
        self._rr_index: Dict[Tuple[str, str], int] = defaultdict(int)
        self._consumer_registry: Dict[str, Tuple[str, str]] = {}
        self._pending_condition = threading.Condition(self._wq_lock)
        self._closed_wq = False

        self._reaper_running = False
        self._reaper_thread: Optional[threading.Thread] = None

    def enqueue(
        self,
        topic: str,
        payload: Any,
        visibility_timeout: Optional[float] = None,
        **headers,
    ) -> str:
        """Put a message on the work queue for the given topic.

        Args:
            topic: Destination topic
            payload: Message payload
            visibility_timeout: Per-message visibility timeout override
            **headers: Additional message headers

        Returns:
            message_id (str)

        Raises:
            QueueFullError: If max_work_queue_size > 0 and queue is full
        """
        vt = (
            visibility_timeout
            if visibility_timeout is not None
            else self._default_visibility_timeout
        )
        message = Message(
            topic=topic,
            payload=payload,
            headers={
                "_wq_retry_count": 0,
                "_wq_original_topic": topic,
                "_wq_enqueued_at": datetime.now(timezone.utc).isoformat(),
                "_wq_visibility_timeout": vt,
                **headers,
            },
        )

        with self._wq_lock:
            if (
                self._max_work_queue_size > 0
                and len(self._pending[topic]) >= self._max_work_queue_size
            ):
                raise QueueFullError(
                    f"Work queue for topic '{topic}' is full "
                    f"({self._max_work_queue_size} messages)"
                )
            self._pending[topic].append(message)
            self._pending_condition.notify_all()

        self._try_dispatch(topic)
        return message.id

    def consume(
        self,
        topic: str,
        handler: Callable[[Message], None],
        consumer_group: Optional[str] = None,
    ) -> str:
        """Register a competing consumer (push-based).

        Messages are dispatched round-robin among consumers in the same
        group. If consumer_group is None, a default group for the topic
        is used.

        Args:
            topic: Topic to consume from
            handler: Callback receiving Message instances
            consumer_group: Consumer group name (default: "{topic}.default")

        Returns:
            consumer_id (str) for later removal
        """
        group = consumer_group or f"{topic}.default"
        consumer_id = str(uuid4())

        with self._wq_lock:
            self._consumer_groups[(topic, group)].append(handler)
            self._consumer_registry[consumer_id] = (topic, group)

        self._try_dispatch(topic)
        return consumer_id

    def dequeue(
        self,
        topic: str,
        timeout: Optional[float] = None,
    ) -> Optional[Message]:
        """Pull one message from the work queue (blocking).

        The returned message's headers contain '_wq_delivery_id' which
        must be passed to ack() or nack(). If not ack'd within the
        visibility timeout, the message is automatically requeued.

        Args:
            topic: Topic to dequeue from
            timeout: Max seconds to wait (None = block forever, 0 = non-blocking)

        Returns:
            Message with delivery tracking headers, or None on timeout
        """
        deadline = None
        if timeout is not None:
            deadline = time.monotonic() + timeout

        with self._pending_condition:
            while True:
                if self._closed_wq:
                    return None

                if self._pending[topic]:
                    msg = self._pending[topic].popleft()
                    return self._make_in_flight(msg, topic, f"{topic}._pull")

                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    self._pending_condition.wait(timeout=remaining)
                else:
                    self._pending_condition.wait(timeout=1.0)

    def ack(self, delivery_id: str) -> bool:
        """Acknowledge successful processing of a message.

        Args:
            delivery_id: The '_wq_delivery_id' from the message headers

        Returns:
            True if the message was in-flight and is now ack'd,
            False if delivery_id not found (already ack'd, expired, etc.)
        """
        with self._wq_lock:
            if delivery_id in self._in_flight:
                del self._in_flight[delivery_id]
                return True
            return False

    def nack(
        self,
        delivery_id: str,
        requeue: bool = True,
    ) -> bool:
        """Reject a message.

        Args:
            delivery_id: The '_wq_delivery_id' from the message headers
            requeue: If True, put back on the queue for redelivery.
                     If False (or max retries exceeded), send to dead letter.

        Returns:
            True if the message was in-flight and is now nack'd,
            False if delivery_id not found
        """
        dispatch_topic = None
        with self._wq_lock:
            entry = self._in_flight.pop(delivery_id, None)
            if entry is None:
                return False

            new_retry = entry.retry_count + 1
            if requeue and new_retry < self._max_retries:
                new_headers = {
                    **entry.message.headers,
                    "_wq_retry_count": new_retry,
                }
                requeued = entry.message.model_copy(update={"headers": new_headers})
                self._pending[entry.topic].appendleft(requeued)
                self._pending_condition.notify_all()
                dispatch_topic = entry.topic
            else:
                reason = (
                    "max_retries_exceeded"
                    if new_retry >= self._max_retries
                    else "nack_no_requeue"
                )
                self._dead_letter(entry.message, entry.topic, reason)

        if dispatch_topic is not None:
            self._try_dispatch(dispatch_topic)

        return True

    def remove_consumer(self, consumer_id: str) -> bool:
        """Remove a previously registered consumer.

        Args:
            consumer_id: ID returned by consume()

        Returns:
            True if found and removed
        """
        with self._wq_lock:
            key = self._consumer_registry.pop(consumer_id, None)
            if key is None:
                return False
            handlers = self._consumer_groups.get(key)
            if handlers:
                handlers.pop()
                if not handlers:
                    del self._consumer_groups[key]
                    self._rr_index.pop(key, None)
            return True

    def pending_count(self, topic: str) -> int:
        """Return number of pending (not yet delivered) messages for topic."""
        with self._wq_lock:
            return len(self._pending[topic])

    def in_flight_count(self, topic: Optional[str] = None) -> int:
        """Return number of in-flight (delivered, not ack'd) messages."""
        with self._wq_lock:
            if topic is None:
                return len(self._in_flight)
            return sum(
                1 for entry in self._in_flight.values() if entry.topic == topic
            )

    def close(self) -> None:
        """Stop reaper thread and close transport."""
        self._reaper_running = False
        self._closed_wq = True
        if self._reaper_thread is not None:
            self._reaper_thread.join(timeout=5.0)
            self._reaper_thread = None
        with self._wq_lock:
            self._pending.clear()
            self._in_flight.clear()
            self._consumer_groups.clear()
            self._consumer_registry.clear()
            self._pending_condition.notify_all()
        super().close()

    # --- Internal helpers ---

    def _make_in_flight(
        self, msg: Message, topic: str, consumer_group: str
    ) -> Message:
        """Stamp a message with a delivery_id, record it in-flight, and return it."""
        delivery_id = str(uuid4())
        vt = msg.headers.get(
            "_wq_visibility_timeout", self._default_visibility_timeout
        )
        retry_count = msg.headers.get("_wq_retry_count", 0)

        new_headers = {**msg.headers, "_wq_delivery_id": delivery_id}
        delivered = msg.model_copy(update={"headers": new_headers})

        entry = InFlightEntry(
            message=msg,
            delivery_id=delivery_id,
            topic=topic,
            consumer_group=consumer_group,
            delivered_at=time.monotonic(),
            visibility_timeout=vt,
            retry_count=retry_count,
        )
        self._in_flight[delivery_id] = entry
        self._start_reaper_if_needed()
        return delivered

    def _try_dispatch(self, topic: str) -> None:
        """Try to dispatch pending messages to push-consumers for a topic."""
        to_invoke: List[Tuple[Callable, Message, str]] = []

        with self._wq_lock:
            groups = [
                key for key in self._consumer_groups if key[0] == topic
            ]
            if not groups:
                return

            while self._pending[topic]:
                msg = self._pending[topic].popleft()
                dispatched = False

                for key in groups:
                    handlers = self._consumer_groups.get(key)
                    if not handlers:
                        continue

                    if len(groups) > 1:
                        msg_copy = msg.model_copy(update={"id": str(uuid4())})
                    else:
                        msg_copy = msg

                    delivered = self._make_in_flight(msg_copy, topic, key[1])
                    idx = self._rr_index[key] % len(handlers)
                    handler = handlers[idx]
                    self._rr_index[key] = idx + 1
                    dispatched = True

                    delivery_id = delivered.headers["_wq_delivery_id"]
                    to_invoke.append((handler, delivered, delivery_id))

                if not dispatched:
                    self._pending[topic].appendleft(msg)
                    break

        # Call handlers outside lock to avoid deadlocks
        for handler, delivered, delivery_id in to_invoke:
            threading.Thread(
                target=self._invoke_handler,
                args=(handler, delivered, delivery_id),
                daemon=True,
            ).start()

    def _invoke_handler(
        self, handler: Callable, message: Message, delivery_id: str
    ) -> None:
        """Invoke a push-consumer handler, auto-nacking on exception."""
        try:
            handler(message)
        except Exception:
            self.nack(delivery_id, requeue=True)

    def _dead_letter(self, message: Message, topic: str, reason: str) -> None:
        """Send a message to the dead-letter topic.

        Must be called while holding self._wq_lock.
        """
        dl_topic = f"{topic}.dead_letter"
        new_headers = {
            **message.headers,
            "_wq_dead_lettered_at": datetime.now(timezone.utc).isoformat(),
            "_wq_dead_letter_reason": reason,
            "_wq_original_topic": message.headers.get(
                "_wq_original_topic", topic
            ),
        }
        dl_msg = message.model_copy(
            update={
                "topic": dl_topic,
                "headers": new_headers,
                "id": str(uuid4()),
            }
        )
        self._pending[dl_topic].append(dl_msg)
        self._pending_condition.notify_all()

    def _start_reaper_if_needed(self) -> None:
        """Lazily start the visibility timeout reaper thread."""
        if self._reaper_running:
            return
        self._reaper_running = True
        self._reaper_thread = threading.Thread(
            target=self._reaper_loop, daemon=True
        )
        self._reaper_thread.start()

    def _reaper_loop(self) -> None:
        """Background thread that requeues messages past their visibility timeout."""
        while self._reaper_running:
            now = time.monotonic()
            expired: List[InFlightEntry] = []

            with self._wq_lock:
                for delivery_id, entry in list(self._in_flight.items()):
                    if now - entry.delivered_at >= entry.visibility_timeout:
                        expired.append(entry)
                        del self._in_flight[delivery_id]

                for entry in expired:
                    new_retry = entry.retry_count + 1
                    if new_retry < self._max_retries:
                        new_headers = {
                            **entry.message.headers,
                            "_wq_retry_count": new_retry,
                        }
                        requeued = entry.message.model_copy(
                            update={"headers": new_headers}
                        )
                        self._pending[entry.topic].appendleft(requeued)
                    else:
                        self._dead_letter(
                            entry.message,
                            entry.topic,
                            "visibility_timeout_exceeded",
                        )

                if expired:
                    self._pending_condition.notify_all()

            time.sleep(self._reaper_interval)
