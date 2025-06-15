#!/usr/bin/env python3
"""
Core message queue implementation.
Provides publish-subscribe patterns with CallPyBack integration.
"""

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from callpyback import CallPyBack
from callpyback.core.context import ExecutionContext
from callpyback.observers.base import BaseObserver

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Message container for pub-sub system."""

    id: str = field(default_factory=lambda: str(uuid4()))
    topic: str = ""
    payload: Any = None
    headers: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    sender: Optional[str] = None
    reply_to: Optional[str] = None
    correlation_id: Optional[str] = None


@dataclass
class Subscription:
    """Subscription container."""

    id: str
    topic: str
    callback: Callable
    filters: Dict[str, Any] = field(default_factory=dict)
    max_retries: int = 3
    retry_count: int = 0
    active: bool = True


class MessageQueueObserver(BaseObserver):
    """Observer for message queue execution tracking."""

    def __init__(self, message_queue: "MessageQueue"):
        super().__init__(priority=90, name="MessageQueueObserver")
        self.message_queue = message_queue
        self.execution_stats = defaultdict(
            lambda: {"success": 0, "failure": 0, "total_time": 0.0}
        )

    def update(self, context: ExecutionContext):
        """Track message processing."""
        if context.state.name == "COMPLETED":
            topic = context.metadata.get("message_topic", "unknown")
            subscription_id = context.metadata.get("subscription_id", "unknown")

            stats = self.execution_stats[f"{topic}:{subscription_id}"]

            if context.is_successful:
                stats["success"] += 1
            else:
                stats["failure"] += 1

            if context.result and hasattr(context.result, "execution_time"):
                stats["total_time"] += context.result.execution_time


class MessageQueue:
    """
    Thread-safe publish-subscribe message queue with CallPyBack integration.

    Features:
    - Topic-based message routing
    - Multiple subscribers per topic
    - Message filtering and priority
    - Retry logic with backoff
    - Dead letter queue support
    - Statistics and monitoring
    """

    def __init__(
        self,
        max_workers: int = 4,
        enable_dead_letter: bool = True,
        message_ttl: float = 3600.0,
    ):
        """
        Initialize MessageQueue.

        Args:
            max_workers: Maximum concurrent workers
            enable_dead_letter: Enable dead letter queue
            message_ttl: Message time-to-live in seconds
        """
        self.max_workers = max_workers
        self.enable_dead_letter = enable_dead_letter
        self.message_ttl = message_ttl

        # Core data structures
        self.subscriptions: Dict[str, List[Subscription]] = defaultdict(list)
        self.dead_letter_queue: List[Message] = []
        self.message_history: List[Message] = []

        # Threading primitives
        self.lock = threading.RLock()
        self.running = False
        self.worker_threads: List[threading.Thread] = []
        self.message_queues: Dict[str, List[Message]] = defaultdict(list)

        # Statistics
        self.stats = {
            "messages_published": 0,
            "messages_processed": 0,
            "messages_failed": 0,
            "subscriptions_active": 0,
        }

        # Observer for tracking
        self.observer = MessageQueueObserver(self)

    def start(self):
        """Start message queue processing."""
        with self.lock:
            if self.running:
                return

            self.running = True

            # Start worker threads
            for i in range(self.max_workers):
                worker = threading.Thread(
                    target=self._worker_loop,
                    name=f"MessageQueue-Worker-{i}",
                    daemon=True,
                )
                worker.start()
                self.worker_threads.append(worker)

            logger.info(f"MessageQueue started with {self.max_workers} workers")

    def stop(self, timeout: float = 5.0):
        """Stop message queue processing."""
        with self.lock:
            if not self.running:
                return

            self.running = False

        # Wait for workers to finish
        for worker in self.worker_threads:
            worker.join(timeout=timeout)

        self.worker_threads.clear()
        logger.info("MessageQueue stopped")

    def subscribe(
        self,
        topic: str,
        callback: Callable,
        filters: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> str:
        """
        Subscribe to a topic.

        Args:
            topic: Topic to subscribe to
            callback: Callback function (will be wrapped in CallPyBack if needed)
            filters: Optional message filters
            max_retries: Maximum retry attempts

        Returns:
            Subscription ID
        """
        subscription = Subscription(
            id=str(uuid4()),
            topic=topic,
            callback=callback,
            filters=filters or {},
            max_retries=max_retries,
        )

        with self.lock:
            self.subscriptions[topic].append(subscription)
            self.stats["subscriptions_active"] += 1

        logger.debug(f"Subscribed to topic '{topic}' with ID {subscription.id}")
        return subscription.id

    def unsubscribe(self, subscription_id: str) -> bool:
        """
        Unsubscribe from a topic.

        Args:
            subscription_id: Subscription ID to remove

        Returns:
            True if subscription was found and removed
        """
        with self.lock:
            for topic, subscriptions in self.subscriptions.items():
                for i, sub in enumerate(subscriptions):
                    if sub.id == subscription_id:
                        subscriptions.pop(i)
                        self.stats["subscriptions_active"] -= 1
                        logger.debug(
                            f"Unsubscribed {subscription_id} from topic '{topic}'"
                        )
                        return True
        return False

    def publish(
        self,
        topic: str,
        payload: Any = None,
        headers: Optional[Dict[str, Any]] = None,
        sender: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> str:
        """
        Publish a message to a topic.

        Args:
            topic: Topic to publish to
            payload: Message payload
            headers: Optional headers
            sender: Sender identifier
            reply_to: Reply-to topic

        Returns:
            Message ID
        """
        message = Message(
            topic=topic,
            payload=payload,
            headers=headers or {},
            sender=sender,
            reply_to=reply_to,
        )

        with self.lock:
            self.message_queues[topic].append(message)
            self.message_history.append(message)
            self.stats["messages_published"] += 1

        logger.debug(f"Published message {message.id} to topic '{topic}'")
        return message.id

    def _worker_loop(self):
        """Main worker thread loop."""
        while self.running:
            try:
                message = self._get_next_message()
                if message:
                    self._process_message(message)
                else:
                    time.sleep(0.01)  # Brief pause when no messages

            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
                time.sleep(0.1)

    def _get_next_message(self) -> Optional[Message]:
        """Get next message to process."""
        with self.lock:
            for topic, messages in self.message_queues.items():
                if messages:
                    return messages.pop(0)
        return None

    def _process_message(self, message: Message):
        """Process a single message."""
        with self.lock:
            subscriptions = self.subscriptions.get(message.topic, [])

        for subscription in subscriptions:
            if not subscription.active:
                continue

            if not self._message_matches_filters(message, subscription.filters):
                continue

            try:
                # Execute callback with context
                subscription.callback(message)
                #    message_topic=message.topic,
                #    subscription_id=subscription.id,
                self.stats["messages_processed"] += 1

            except Exception as e:
                self._handle_message_error(message, subscription, e)

    def _message_matches_filters(
        self, message: Message, filters: Dict[str, Any]
    ) -> bool:
        """Check if message matches subscription filters."""
        if not filters:
            return True

        for key, expected_value in filters.items():
            if key == "sender" and message.sender != expected_value:
                return False
            elif key in message.headers and message.headers[key] != expected_value:
                return False

        return True

    def _handle_message_error(
        self, message: Message, subscription: Subscription, error: Exception
    ):
        """Handle message processing error."""
        subscription.retry_count += 1
        self.stats["messages_failed"] += 1

        if subscription.retry_count <= subscription.max_retries:
            # Retry message
            with self.lock:
                self.message_queues[message.topic].append(message)
            logger.debug(
                f"Retrying message {message.id} (attempt {subscription.retry_count})"
            )
        else:
            # Send to dead letter queue
            if self.enable_dead_letter:
                with self.lock:
                    self.dead_letter_queue.append(message)

            logger.warning(
                f"Message {message.id} sent to dead letter queue after {subscription.retry_count} failures"
            )

    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        with self.lock:
            queue_lengths = {
                topic: len(msgs) for topic, msgs in self.message_queues.items()
            }

            return {
                **self.stats,
                "queue_lengths": queue_lengths,
                "dead_letter_count": len(self.dead_letter_queue),
                "total_subscriptions": sum(
                    len(subs) for subs in self.subscriptions.values()
                ),
                "observer_stats": dict(self.observer.execution_stats),
            }

    def get_topics(self) -> List[str]:
        """Get list of active topics."""
        with self.lock:
            return list(self.subscriptions.keys())

    def clear_dead_letter_queue(self):
        """Clear dead letter queue."""
        with self.lock:
            self.dead_letter_queue.clear()
