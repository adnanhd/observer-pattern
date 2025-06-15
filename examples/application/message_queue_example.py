#!/usr/bin/env python3
"""
Message Queue/Pub-Sub Monitoring Example
Demonstrates monitoring message processing with CallPyBack for:
- Message queue throughput tracking
- Publisher/subscriber monitoring
- Message processing latency
- Dead letter queue management
- Queue health and backlog monitoring
"""

import json
import random
import threading
import time
import uuid
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from queue import Empty, Queue
from typing import Any, Callable, Dict, List, Optional

from callpyback import (
    CallPyBack,
    DefaultErrorHandler,
    ExecutionContext,
    ExecutionState,
    on_call,
    on_completion,
    on_failure,
    on_success,
)
from callpyback.observers.base import BaseObserver


class MessageStatus(Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"
    RETRYING = "RETRYING"


class QueueType(Enum):
    FIFO = "FIFO"
    PRIORITY = "PRIORITY"
    TOPIC = "TOPIC"
    DEAD_LETTER = "DEAD_LETTER"


@dataclass
class Message:
    message_id: str
    topic: str
    payload: Dict[str, Any]
    headers: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    priority: int = 1
    retry_count: int = 0
    max_retries: int = 3
    status: MessageStatus = MessageStatus.PENDING
    processing_time: Optional[float] = None
    error_message: Optional[str] = None


@dataclass
class Subscription:
    subscriber_id: str
    topic_pattern: str
    handler: Callable
    active: bool = True
    message_count: int = 0
    last_message_time: Optional[float] = None


class MessageQueueObserver(BaseObserver):
    """Monitor message queue operations and performance"""

    def __init__(self):
        super().__init__(priority=95, name="MessageQueue")
        self.queue_stats = defaultdict(
            lambda: {
                "messages_published": 0,
                "messages_consumed": 0,
                "messages_failed": 0,
                "total_processing_time": 0,
                "backlog_size": 0,
                "throughput_history": deque(maxlen=100),
                "error_rate_history": deque(maxlen=50),
            }
        )
        self.topic_stats = defaultdict(
            lambda: {
                "publishers": set(),
                "subscribers": set(),
                "message_count": 0,
                "avg_message_size": 0,
                "total_bytes": 0,
            }
        )
        self.processing_latencies = deque(maxlen=500)
        self.dead_letter_messages = deque(maxlen=100)
        self.lock = threading.Lock()

    def update(self, context: ExecutionContext) -> None:
        if context.state != ExecutionState.COMPLETED:
            return

        operation_type = context.arguments.get("operation_type")
        message = context.arguments.get("message")
        topic = context.arguments.get("topic", "unknown")

        if not operation_type:
            return

        with self.lock:
            current_time = time.time()

            # Update queue statistics
            queue_stats = self.queue_stats[topic]
            topic_stats = self.topic_stats[topic]

            if operation_type == "publish":
                queue_stats["messages_published"] += 1
                topic_stats["message_count"] += 1

                if message:
                    # Track message size
                    message_size = len(json.dumps(message.payload).encode("utf-8"))
                    topic_stats["total_bytes"] += message_size
                    topic_stats["avg_message_size"] = (
                        topic_stats["total_bytes"] / topic_stats["message_count"]
                    )

                    # Track publisher
                    publisher_id = context.arguments.get("publisher_id", "unknown")
                    topic_stats["publishers"].add(publisher_id)

            elif operation_type == "consume":
                queue_stats["messages_consumed"] += 1

                if context.result:
                    processing_time = getattr(context.result, "execution_time", 0)
                    queue_stats["total_processing_time"] += processing_time
                    self.processing_latencies.append(processing_time)

                    if context.is_successful:
                        # Track successful processing
                        subscriber_id = context.arguments.get(
                            "subscriber_id", "unknown"
                        )
                        topic_stats["subscribers"].add(subscriber_id)
                    else:
                        # Track failed processing
                        queue_stats["messages_failed"] += 1

                        if message and message.retry_count >= message.max_retries:
                            # Move to dead letter queue
                            self.dead_letter_messages.append(
                                {
                                    "message_id": message.message_id,
                                    "topic": topic,
                                    "error": str(
                                        getattr(
                                            context.result, "exception", "Unknown error"
                                        )
                                    ),
                                    "retry_count": message.retry_count,
                                    "timestamp": current_time,
                                }
                            )

            # Update throughput tracking
            queue_stats["throughput_history"].append(
                {
                    "timestamp": current_time,
                    "operation": operation_type,
                    "success": context.is_successful,
                }
            )

            # Update error rate every 10 messages
            if queue_stats["messages_consumed"] % 10 == 0:
                recent_messages = queue_stats["messages_consumed"]
                recent_failures = queue_stats["messages_failed"]
                error_rate = (
                    (recent_failures / recent_messages) * 100
                    if recent_messages > 0
                    else 0
                )
                queue_stats["error_rate_history"].append(error_rate)

    def get_queue_health_report(self):
        """Generate queue health and performance report"""
        with self.lock:
            report = {}

            for topic, stats in self.queue_stats.items():
                # Calculate metrics
                total_messages = stats["messages_consumed"]
                avg_processing_time = (
                    stats["total_processing_time"] / total_messages
                    if total_messages > 0
                    else 0
                )
                error_rate = (
                    stats["messages_failed"] / total_messages * 100
                    if total_messages > 0
                    else 0
                )

                # Calculate throughput (messages per second over last minute)
                current_time = time.time()
                recent_ops = [
                    op
                    for op in stats["throughput_history"]
                    if current_time - op["timestamp"] < 60
                ]
                throughput = len(recent_ops) / 60 if recent_ops else 0

                # Determine health status
                if error_rate > 20:
                    health_status = "CRITICAL"
                elif error_rate > 10 or avg_processing_time > 5.0:
                    health_status = "WARNING"
                elif throughput == 0:
                    health_status = "IDLE"
                else:
                    health_status = "HEALTHY"

                report[topic] = {
                    "health_status": health_status,
                    "messages_published": stats["messages_published"],
                    "messages_consumed": stats["messages_consumed"],
                    "messages_failed": stats["messages_failed"],
                    "error_rate": f"{error_rate:.1f}%",
                    "avg_processing_time": f"{avg_processing_time:.3f}s",
                    "throughput": f"{throughput:.1f} msg/s",
                    "backlog_size": stats["backlog_size"],
                }

            return report

    def get_topic_analytics(self):
        """Get topic usage analytics"""
        with self.lock:
            analytics = {}

            for topic, stats in self.topic_stats.items():
                analytics[topic] = {
                    "publishers": len(stats["publishers"]),
                    "subscribers": len(stats["subscribers"]),
                    "total_messages": stats["message_count"],
                    "avg_message_size": f"{stats['avg_message_size']:.1f} bytes",
                    "total_data": f"{self._format_bytes(stats['total_bytes'])}",
                }

            return analytics

    def get_processing_latency_analysis(self):
        """Analyze message processing latencies"""
        with self.lock:
            if not self.processing_latencies:
                return {}

            latencies = sorted(self.processing_latencies)
            count = len(latencies)

            return {
                "total_messages": count,
                "avg_latency": f"{sum(latencies) / count:.3f}s",
                "min_latency": f"{min(latencies):.3f}s",
                "max_latency": f"{max(latencies):.3f}s",
                "p50_latency": f"{latencies[count // 2]:.3f}s",
                "p95_latency": f"{latencies[int(count * 0.95)]:.3f}s",
                "p99_latency": f"{latencies[int(count * 0.99)]:.3f}s",
            }

    def get_dead_letter_queue_status(self):
        """Get dead letter queue status"""
        with self.lock:
            if not self.dead_letter_messages:
                return {"count": 0, "messages": []}

            # Group by error type
            error_patterns = defaultdict(int)
            for msg in self.dead_letter_messages:
                error_type = (
                    msg["error"].split(":")[0]
                    if ":" in msg["error"]
                    else msg["error"][:30]
                )
                error_patterns[error_type] += 1

            return {
                "count": len(self.dead_letter_messages),
                "error_patterns": dict(error_patterns),
                "recent_messages": list(self.dead_letter_messages)[
                    -5:
                ],  # Last 5 messages
            }

    @staticmethod
    def _format_bytes(bytes_val):
        """Format bytes in human readable format"""
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} TB"


class SubscriberMonitor(BaseObserver):
    """Monitor subscriber performance and health"""

    def __init__(self):
        super().__init__(priority=85, name="SubscriberMonitor")
        self.subscriber_stats = defaultdict(
            lambda: {
                "messages_processed": 0,
                "processing_errors": 0,
                "total_processing_time": 0,
                "last_active": None,
                "subscribed_topics": set(),
                "avg_processing_time": 0,
            }
        )
        self.lock = threading.Lock()

    def update(self, context: ExecutionContext) -> None:
        if context.state != ExecutionState.COMPLETED:
            return

        subscriber_id = context.arguments.get("subscriber_id")
        topic = context.arguments.get("topic")
        operation_type = context.arguments.get("operation_type")

        if not subscriber_id or operation_type != "consume":
            return

        with self.lock:
            stats = self.subscriber_stats[subscriber_id]
            stats["messages_processed"] += 1
            stats["last_active"] = time.time()

            if topic:
                stats["subscribed_topics"].add(topic)

            if context.result:
                processing_time = getattr(context.result, "execution_time", 0)
                stats["total_processing_time"] += processing_time
                stats["avg_processing_time"] = (
                    stats["total_processing_time"] / stats["messages_processed"]
                )

                if not context.is_successful:
                    stats["processing_errors"] += 1

    def get_subscriber_report(self):
        """Generate subscriber performance report"""
        with self.lock:
            report = {}
            current_time = time.time()

            for subscriber_id, stats in self.subscriber_stats.items():
                last_active_ago = (
                    current_time - stats["last_active"]
                    if stats["last_active"]
                    else None
                )
                error_rate = (
                    stats["processing_errors"] / stats["messages_processed"] * 100
                    if stats["messages_processed"] > 0
                    else 0
                )

                # Determine subscriber health
                if last_active_ago is None or last_active_ago > 300:  # 5 minutes
                    health = "INACTIVE"
                elif error_rate > 15:
                    health = "UNHEALTHY"
                elif error_rate > 5:
                    health = "DEGRADED"
                else:
                    health = "HEALTHY"

                report[subscriber_id] = {
                    "health": health,
                    "messages_processed": stats["messages_processed"],
                    "error_rate": f"{error_rate:.1f}%",
                    "avg_processing_time": f"{stats['avg_processing_time']:.3f}s",
                    "subscribed_topics": list(stats["subscribed_topics"]),
                    "last_active": (
                        f"{last_active_ago:.1f}s ago" if last_active_ago else "Never"
                    ),
                }

            return report


# Set up monitoring
queue_monitor = MessageQueueObserver()
subscriber_monitor = SubscriberMonitor()

# Error handler for message processing
message_error_handler = DefaultErrorHandler(
    default_return={
        "status": "error",
        "processed": False,
        "error": "Message processing failed",
    }
)


class MockMessageQueue:
    """Mock message queue system"""

    def __init__(self):
        self.queues = defaultdict(lambda: Queue())
        self.dead_letter_queue = Queue()
        self.subscriptions = defaultdict(list)  # topic -> list of subscriptions
        self.running = True
        self.stats = defaultdict(int)
        self.lock = threading.Lock()

    def publish(self, topic: str, message: Message, publisher_id: str = "unknown"):
        """Publish message to topic"""
        with self.lock:
            self.queues[topic].put(message)
            self.stats[f"published_{topic}"] += 1
            print(f"📤 Published: {message.message_id} to {topic}")

    def subscribe(self, subscriber_id: str, topic_pattern: str, handler: Callable):
        """Subscribe to topic"""
        subscription = Subscription(subscriber_id, topic_pattern, handler)
        self.subscriptions[topic_pattern].append(subscription)
        print(f"📥 Subscribed: {subscriber_id} to {topic_pattern}")
        return subscription

    def consume_messages(self, topic: str, subscriber_id: str, timeout: float = 1.0):
        """Consume messages from topic"""
        try:
            message = self.queues[topic].get(timeout=timeout)
            self.stats[f"consumed_{topic}"] += 1
            return message
        except Empty:
            return None

    def get_queue_size(self, topic: str) -> int:
        """Get current queue size"""
        return self.queues[topic].qsize()

    def get_stats(self):
        """Get queue statistics"""
        with self.lock:
            return dict(self.stats)


# Mock message queue instance
message_queue = MockMessageQueue()


@CallPyBack(
    observers=[
        queue_monitor,
        on_call(
            lambda context: print(
                f"📨 Processing: {context.arguments.get('operation_type', 'unknown')} - {context.arguments.get('message', {}).message_id if context.arguments.get('message') else 'N/A'}"
            )
        ),
        on_failure(
            lambda result: print(f"❌ Message processing failed: {result.exception}")
        ),
    ],
    error_handler=message_error_handler,
    exception_classes=(RuntimeError, ValueError, ConnectionError),
    variable_names=["processing_stage", "validation_result", "transform_result"],
)
def publish_message(
    topic: str, message: Message, publisher_id: str = "publisher"
) -> Dict[str, Any]:
    """Publish a message to the queue with monitoring"""

    processing_stage = "validating"
    validation_result = None

    # Validate message
    if not message.payload:
        raise ValueError("Message payload cannot be empty")

    validation_result = "valid"
    processing_stage = "publishing"

    # Simulate publishing latency
    time.sleep(random.uniform(0.001, 0.01))

    # Publish to queue
    message_queue.publish(topic, message, publisher_id)

    # Update queue backlog size in monitoring
    with queue_monitor.lock:
        queue_monitor.queue_stats[topic]["backlog_size"] = message_queue.get_queue_size(
            topic
        )

    processing_stage = "completed"

    return {
        "message_id": message.message_id,
        "topic": topic,
        "publisher_id": publisher_id,
        "status": "published",
        "queue_size": message_queue.get_queue_size(topic),
    }


@CallPyBack(
    observers=[
        queue_monitor,
        subscriber_monitor,
        on_failure(
            lambda result: print(f"❌ Message consumption failed: {result.exception}")
        ),
    ],
    error_handler=message_error_handler,
    exception_classes=(RuntimeError, ValueError, TimeoutError),
    variable_names=["message_data", "processing_result", "retry_decision"],
)
def consume_message(
    topic: str, subscriber_id: str, timeout: float = 1.0
) -> Dict[str, Any]:
    """Consume and process a message from the queue with monitoring"""

    message_data = None
    processing_result = None
    retry_decision = None

    # Get message from queue
    message = message_queue.consume_messages(topic, subscriber_id, timeout)

    if not message:
        return {
            "subscriber_id": subscriber_id,
            "topic": topic,
            "status": "no_message",
            "processed": False,
        }

    message_data = message.payload
    message.status = MessageStatus.PROCESSING

    try:
        # Simulate message processing
        processing_time = random.uniform(0.05, 0.5)
        time.sleep(processing_time)

        # Simulate processing logic based on message type
        message_type = message.payload.get("type", "unknown")

        if message_type == "user_event":
            processing_result = process_user_event(message.payload)
        elif message_type == "order_event":
            processing_result = process_order_event(message.payload)
        elif message_type == "notification":
            processing_result = process_notification(message.payload)
        elif message_type == "analytics":
            processing_result = process_analytics_event(message.payload)
        else:
            processing_result = {"processed": True, "handler": "generic"}

        # Simulate random processing failures
        if random.random() < 0.12:  # 12% failure rate
            error_types = [
                "Invalid message format",
                "Database connection failed",
                "External service timeout",
                "Processing limit exceeded",
                "Validation failed",
            ]
            raise RuntimeError(random.choice(error_types))

        message.status = MessageStatus.PROCESSED
        message.processing_time = processing_time

        # Update queue backlog size
        with queue_monitor.lock:
            queue_monitor.queue_stats[topic]["backlog_size"] = (
                message_queue.get_queue_size(topic)
            )

        return {
            "message_id": message.message_id,
            "subscriber_id": subscriber_id,
            "topic": topic,
            "status": "processed",
            "processing_time": processing_time,
            "result": processing_result,
            "processed": True,
        }

    except Exception as e:
        message.status = MessageStatus.FAILED
        message.error_message = str(e)

        # Retry logic
        if message.retry_count < message.max_retries:
            message.retry_count += 1
            message.status = MessageStatus.RETRYING
            retry_decision = f"retry_{message.retry_count}"

            # Re-queue for retry (with exponential backoff)
            time.sleep(0.1 * (2**message.retry_count))
            message_queue.publish(topic, message, "retry_publisher")

            print(
                f"🔄 Retrying message {message.message_id} (attempt {message.retry_count + 1})"
            )
        else:
            message.status = MessageStatus.DEAD_LETTER
            retry_decision = "dead_letter"
            message_queue.dead_letter_queue.put(message)

        raise


def process_user_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process user-related events"""
    event_type = payload.get("event_type", "unknown")
    user_id = payload.get("user_id", "anonymous")

    # Simulate different processing based on event type
    if event_type == "login":
        return {
            "action": "user_login_processed",
            "user_id": user_id,
            "session_created": True,
        }
    elif event_type == "logout":
        return {
            "action": "user_logout_processed",
            "user_id": user_id,
            "session_ended": True,
        }
    elif event_type == "profile_update":
        return {
            "action": "profile_updated",
            "user_id": user_id,
            "fields_updated": payload.get("fields", []),
        }
    else:
        return {"action": "generic_user_event", "user_id": user_id}


def process_order_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process order-related events"""
    order_id = payload.get("order_id", "unknown")
    event_type = payload.get("event_type", "unknown")

    if event_type == "order_created":
        return {
            "action": "order_created",
            "order_id": order_id,
            "inventory_reserved": True,
        }
    elif event_type == "payment_processed":
        return {
            "action": "payment_completed",
            "order_id": order_id,
            "payment_confirmed": True,
        }
    elif event_type == "order_shipped":
        return {
            "action": "shipping_initiated",
            "order_id": order_id,
            "tracking_number": f"TRK-{order_id}",
        }
    else:
        return {"action": "generic_order_event", "order_id": order_id}


def process_notification(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process notification messages"""
    notification_type = payload.get("type", "email")
    recipient = payload.get("recipient", "unknown")

    # Simulate sending notification
    if notification_type == "email":
        return {
            "sent": True,
            "method": "email",
            "recipient": recipient,
            "delivery_id": f"email_{uuid.uuid4().hex[:8]}",
        }
    elif notification_type == "sms":
        return {
            "sent": True,
            "method": "sms",
            "recipient": recipient,
            "delivery_id": f"sms_{uuid.uuid4().hex[:8]}",
        }
    elif notification_type == "push":
        return {
            "sent": True,
            "method": "push",
            "recipient": recipient,
            "delivery_id": f"push_{uuid.uuid4().hex[:8]}",
        }
    else:
        return {"sent": True, "method": "generic", "recipient": recipient}


def process_analytics_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process analytics events"""
    event_name = payload.get("event", "unknown")
    user_id = payload.get("user_id", "anonymous")

    return {
        "recorded": True,
        "event": event_name,
        "user_id": user_id,
        "timestamp": time.time(),
        "analytics_id": f"analytics_{uuid.uuid4().hex[:8]}",
    }


def create_sample_messages(count: int = 50) -> List[Message]:
    """Create sample messages for testing"""
    messages = []

    message_types = [
        ("user_event", ["login", "logout", "profile_update", "registration"]),
        (
            "order_event",
            ["order_created", "payment_processed", "order_shipped", "order_cancelled"],
        ),
        ("notification", ["email", "sms", "push"]),
        ("analytics", ["page_view", "button_click", "purchase", "search"]),
    ]

    for i in range(count):
        message_type, event_subtypes = random.choice(message_types)
        event_subtype = random.choice(event_subtypes)

        payload = {
            "type": message_type,
            "event_type": event_subtype,
            "user_id": f"user_{random.randint(1, 100)}",
            "timestamp": time.time(),
            "data": f"sample_data_{i}",
        }

        # Add type-specific fields
        if message_type == "order_event":
            payload["order_id"] = f"order_{random.randint(1000, 9999)}"
            payload["amount"] = random.randint(10, 500)
        elif message_type == "notification":
            payload["recipient"] = f"user_{random.randint(1, 100)}@example.com"
            payload["message"] = f"Sample notification message {i}"
        elif message_type == "analytics":
            payload["event"] = event_subtype
            payload["properties"] = {"page": f"/page_{i}", "source": "web"}

        message = Message(
            message_id=f"msg_{i:04d}_{uuid.uuid4().hex[:8]}",
            topic=message_type,
            payload=payload,
            priority=random.randint(1, 5),
            max_retries=random.randint(1, 3),
        )

        messages.append(message)

    return messages


def simulate_publishers(messages: List[Message], publisher_count: int = 3):
    """Simulate multiple publishers"""

    print(f"📤 Starting {publisher_count} publishers with {len(messages)} messages")

    # Distribute messages among publishers
    messages_per_publisher = len(messages) // publisher_count
    publisher_results = []

    with ThreadPoolExecutor(
        max_workers=publisher_count, thread_name_prefix="Publisher"
    ) as executor:
        futures = []

        for i in range(publisher_count):
            start_idx = i * messages_per_publisher
            end_idx = (
                start_idx + messages_per_publisher
                if i < publisher_count - 1
                else len(messages)
            )
            publisher_messages = messages[start_idx:end_idx]
            publisher_id = f"publisher_{i+1}"

            future = executor.submit(run_publisher, publisher_id, publisher_messages)
            futures.append((publisher_id, future))

        # Collect results
        for publisher_id, future in futures:
            try:
                result = future.result(timeout=30)
                publisher_results.append(result)
                print(f"  ✅ {publisher_id}: {result['published']} messages published")
            except Exception as e:
                print(f"  ❌ {publisher_id} failed: {e}")
                publisher_results.append(
                    {"publisher_id": publisher_id, "published": 0, "error": str(e)}
                )

    return publisher_results


def run_publisher(publisher_id: str, messages: List[Message]) -> Dict[str, Any]:
    """Run a single publisher"""
    published_count = 0
    failed_count = 0

    for message in messages:
        try:
            result = publish_message(message.topic, message, publisher_id)
            published_count += 1

            # Small delay between messages
            time.sleep(random.uniform(0.01, 0.05))

        except Exception as e:
            failed_count += 1
            print(
                f"❌ Publisher {publisher_id} failed to publish {message.message_id}: {e}"
            )

    return {
        "publisher_id": publisher_id,
        "published": published_count,
        "failed": failed_count,
        "total": len(messages),
    }


def simulate_subscribers(
    topics: List[str], subscriber_count: int = 4, duration: int = 30
):
    """Simulate multiple subscribers"""

    print(f"📥 Starting {subscriber_count} subscribers for {duration} seconds")

    subscriber_results = []

    with ThreadPoolExecutor(
        max_workers=subscriber_count, thread_name_prefix="Subscriber"
    ) as executor:
        futures = []

        for i in range(subscriber_count):
            subscriber_id = f"subscriber_{i+1}"
            # Assign topics to subscribers (some overlap)
            assigned_topics = random.sample(
                topics, random.randint(1, min(3, len(topics)))
            )

            future = executor.submit(
                run_subscriber, subscriber_id, assigned_topics, duration
            )
            futures.append((subscriber_id, future))

        # Collect results
        for subscriber_id, future in futures:
            try:
                result = future.result(timeout=duration + 10)
                subscriber_results.append(result)
                print(f"  ✅ {subscriber_id}: {result['processed']} messages processed")
            except Exception as e:
                print(f"  ❌ {subscriber_id} failed: {e}")
                subscriber_results.append(
                    {"subscriber_id": subscriber_id, "processed": 0, "error": str(e)}
                )

    return subscriber_results


def run_subscriber(
    subscriber_id: str, topics: List[str], duration: int
) -> Dict[str, Any]:
    """Run a single subscriber"""
    processed_count = 0
    failed_count = 0
    start_time = time.time()

    while time.time() - start_time < duration:
        for topic in topics:
            try:
                result = consume_message(topic, subscriber_id, timeout=0.5)

                if result.get("processed", False):
                    processed_count += 1

                # Small processing delay
                time.sleep(random.uniform(0.01, 0.1))

            except Exception as e:
                failed_count += 1

    return {
        "subscriber_id": subscriber_id,
        "topics": topics,
        "processed": processed_count,
        "failed": failed_count,
        "duration": time.time() - start_time,
    }


def simulate_message_queue_system():
    """Simulate a complete message queue system"""

    print("🚀 Starting Message Queue System Simulation")
    print("=" * 60)

    # Create sample messages
    messages = create_sample_messages(100)
    topics = list(set(msg.topic for msg in messages))

    print(f"📋 Created {len(messages)} messages across {len(topics)} topics")
    print(f"📊 Topics: {', '.join(topics)}")

    # Start publishers
    print(f"\n📤 Phase 1: Publishing Messages")
    publisher_results = simulate_publishers(messages, publisher_count=3)

    # Allow some time for queue to build up
    time.sleep(2)

    # Start subscribers
    print(f"\n📥 Phase 2: Consuming Messages")
    subscriber_results = simulate_subscribers(topics, subscriber_count=4, duration=20)

    # Let subscribers finish processing
    time.sleep(3)

    print(f"\n🏁 Message queue simulation completed")

    # Generate comprehensive analysis
    print("\n" + "=" * 70)
    print("📊 MESSAGE QUEUE SYSTEM ANALYSIS")
    print("=" * 70)

    # Queue health report
    queue_health = queue_monitor.get_queue_health_report()
    print(f"\n🏥 Queue Health Status:")
    for topic, health in queue_health.items():
        status_icon = {
            "HEALTHY": "🟢",
            "WARNING": "🟡",
            "CRITICAL": "🔴",
            "IDLE": "⚫",
        }.get(health["health_status"], "❓")

        print(f"  {status_icon} {topic}:")
        print(f"    Status: {health['health_status']}")
        print(f"    Published: {health['messages_published']}")
        print(f"    Consumed: {health['messages_consumed']}")
        print(f"    Failed: {health['messages_failed']}")
        print(f"    Error Rate: {health['error_rate']}")
        print(f"    Avg Processing: {health['avg_processing_time']}")
        print(f"    Throughput: {health['throughput']}")
        print(f"    Backlog: {health['backlog_size']}")

    # Topic analytics
    topic_analytics = queue_monitor.get_topic_analytics()
    print(f"\n📈 Topic Analytics:")
    for topic, analytics in topic_analytics.items():
        print(f"  📋 {topic}:")
        print(f"    Publishers: {analytics['publishers']}")
        print(f"    Subscribers: {analytics['subscribers']}")
        print(f"    Total Messages: {analytics['total_messages']}")
        print(f"    Avg Message Size: {analytics['avg_message_size']}")
        print(f"    Total Data: {analytics['total_data']}")

    # Processing latency analysis
    latency_analysis = queue_monitor.get_processing_latency_analysis()
    if latency_analysis:
        print(f"\n⏱️  Processing Latency Analysis:")
        print(f"  Total Messages: {latency_analysis['total_messages']}")
        print(f"  Average: {latency_analysis['avg_latency']}")
        print(
            f"  Min/Max: {latency_analysis['min_latency']} / {latency_analysis['max_latency']}"
        )
        print(f"  P50: {latency_analysis['p50_latency']}")
        print(f"  P95: {latency_analysis['p95_latency']}")
        print(f"  P99: {latency_analysis['p99_latency']}")

    # Subscriber performance
    subscriber_report = subscriber_monitor.get_subscriber_report()
    print(f"\n👥 Subscriber Performance:")
    for subscriber_id, report in subscriber_report.items():
        health_icon = {
            "HEALTHY": "🟢",
            "DEGRADED": "🟡",
            "UNHEALTHY": "🔴",
            "INACTIVE": "⚫",
        }.get(report["health"], "❓")

        print(f"  {health_icon} {subscriber_id}:")
        print(f"    Health: {report['health']}")
        print(f"    Messages: {report['messages_processed']}")
        print(f"    Error Rate: {report['error_rate']}")
        print(f"    Avg Processing: {report['avg_processing_time']}")
        print(f"    Topics: {', '.join(report['subscribed_topics'])}")
        print(f"    Last Active: {report['last_active']}")

    # Dead letter queue status
    dlq_status = queue_monitor.get_dead_letter_queue_status()
    if dlq_status["count"] > 0:
        print(f"\n💀 Dead Letter Queue Status:")
        print(f"  Total Dead Letters: {dlq_status['count']}")
        print(f"  Error Patterns:")
        for error_type, count in dlq_status["error_patterns"].items():
            print(f"    {error_type}: {count} messages")

        print(f"  Recent Dead Letters:")
        for msg in dlq_status["recent_messages"]:
            print(f"    {msg['message_id']} ({msg['topic']}): {msg['error']}")
    else:
        print(f"\n✅ No messages in dead letter queue")

    # Publisher summary
    total_published = sum(result.get("published", 0) for result in publisher_results)
    total_pub_failed = sum(result.get("failed", 0) for result in publisher_results)

    print(f"\n📤 Publisher Summary:")
    print(f"  Total Published: {total_published}")
    print(f"  Total Failed: {total_pub_failed}")
    print(
        f"  Success Rate: {(total_published / (total_published + total_pub_failed)) * 100:.1f}%"
    )

    # Subscriber summary
    total_processed = sum(result.get("processed", 0) for result in subscriber_results)
    total_sub_failed = sum(result.get("failed", 0) for result in subscriber_results)

    print(f"\n📥 Subscriber Summary:")
    print(f"  Total Processed: {total_processed}")
    print(f"  Total Failed: {total_sub_failed}")
    print(
        f"  Processing Rate: {(total_processed / (total_processed + total_sub_failed)) * 100:.1f}%"
    )

    # System overview
    print(f"\n🎯 System Overview:")
    print(f"  Messages Created: {len(messages)}")
    print(f"  Messages Published: {total_published}")
    print(f"  Messages Processed: {total_processed}")
    print(f"  End-to-End Success Rate: {(total_processed / len(messages)) * 100:.1f}%")

    # Queue statistics
    queue_stats = message_queue.get_stats()
    if queue_stats:
        print(f"\n📊 Final Queue Statistics:")
        for stat_name, count in queue_stats.items():
            print(f"  {stat_name}: {count}")


if __name__ == "__main__":
    simulate_message_queue_system()
