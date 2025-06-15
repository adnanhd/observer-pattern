#!/usr/bin/env python3
"""
Provides decorators, fluent API, and advanced messaging patterns
"""

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TypeVar
from uuid import uuid4

from callpyback.plugins.core.message_queue import EventBus as BaseEventBus
from callpyback.plugins.core.message_queue import Message
from callpyback.plugins.core.topic_registry import TopicRegistry

T = TypeVar("T")


@dataclass
class EventPattern:
    """Event pattern matching"""

    pattern: str
    exact_match: bool = False
    case_sensitive: bool = True

    def matches(self, topic: str) -> bool:
        """Check if topic matches pattern"""
        if self.exact_match:
            return (
                topic == self.pattern
                if self.case_sensitive
                else topic.lower() == self.pattern.lower()
            )

        # Simple wildcard matching
        pattern = self.pattern if self.case_sensitive else self.pattern.lower()
        topic_check = topic if self.case_sensitive else topic.lower()

        if "*" in pattern:
            # Convert to regex-like matching
            pattern_parts = pattern.split("*")
            current_pos = 0

            for part in pattern_parts:
                if not part:
                    continue
                pos = topic_check.find(part, current_pos)
                if pos == -1:
                    return False
                current_pos = pos + len(part)

            return True

        return pattern in topic_check


@dataclass
class EventHandler:
    """Enhanced event handler with metadata"""

    handler_id: str
    callback: Callable
    pattern: EventPattern
    priority: int = 0
    max_calls: Optional[int] = None
    timeout: Optional[float] = None
    error_handler: Optional[Callable] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    call_count: int = 0
    last_called: Optional[float] = None

    def should_handle(self, topic: str) -> bool:
        """Check if this handler should process the topic"""
        if self.max_calls and self.call_count >= self.max_calls:
            return False
        return self.pattern.matches(topic)

    def __call__(self, message: Message) -> Any:
        """Execute the handler"""
        self.call_count += 1
        self.last_called = time.time()

        try:
            if self.timeout:
                # TODO: Implement timeout mechanism
                pass

            return self.callback(message)
        except Exception as e:
            if self.error_handler:
                return self.error_handler(e, message)
            raise


class EventBuilder:
    """Fluent API for building events"""

    def __init__(self, topic: str):
        self.topic = topic
        self.payload: Any = None
        self.headers: Dict[str, Any] = {}
        self.sender: Optional[str] = None
        self.reply_to: Optional[str] = None
        self.delay: Optional[float] = None
        self.retry_count: int = 0

    def with_payload(self, payload: Any) -> "EventBuilder":
        """Set event payload"""
        self.payload = payload
        return self

    def with_headers(self, **headers) -> "EventBuilder":
        """Add headers to event"""
        self.headers.update(headers)
        return self

    def with_sender(self, sender: str) -> "EventBuilder":
        """Set event sender"""
        self.sender = sender
        return self

    def reply_to_topic(self, reply_topic: str) -> "EventBuilder":
        """Set reply-to topic"""
        self.reply_to = reply_topic
        return self

    def with_delay(self, delay: float) -> "EventBuilder":
        """Add delay before publishing"""
        self.delay = delay
        return self

    def with_retry(self, retry_count: int) -> "EventBuilder":
        """Set retry count for failed deliveries"""
        self.retry_count = retry_count
        return self

    def publish(self, event_bus: "EnhancedEventBus") -> str:
        """Publish the event"""
        if self.delay:
            time.sleep(self.delay)

        return event_bus.publish(
            topic=self.topic,
            payload=self.payload,
            headers=self.headers,
            sender=self.sender,
            reply_to=self.reply_to,
        )


class EnhancedEventBus(BaseEventBus):
    """Enhanced EventBus with syntactic sugar and advanced features"""

    def __init__(self):
        super().__init__()
        self.handlers: Dict[str, List[EventHandler]] = defaultdict(list)
        self.topic_registry = TopicRegistry()
        self.message_history: deque = deque(maxlen=1000)
        self.stats = {
            "events_published": 0,
            "events_handled": 0,
            "handlers_registered": 0,
            "errors": 0,
        }
        self.lock = threading.RLock()

    # Decorator-based registration
    def on(
        self,
        topic_pattern: str,
        priority: int = 0,
        max_calls: Optional[int] = None,
        timeout: Optional[float] = None,
        exact_match: bool = False,
    ):
        """Decorator for registering event handlers"""

        def decorator(func: Callable) -> Callable:
            self.register_handler(
                topic_pattern=topic_pattern,
                callback=func,
                priority=priority,
                max_calls=max_calls,
                timeout=timeout,
                exact_match=exact_match,
            )
            return func

        return decorator

    def once(self, topic_pattern: str, priority: int = 0):
        """Decorator for one-time event handlers"""
        return self.on(topic_pattern, priority=priority, max_calls=1)

    def error_handler(self, topic_pattern: str = "*"):
        """Decorator for error handlers"""

        def decorator(func: Callable) -> Callable:
            def error_callback(message: Message):
                if hasattr(message, "error"):
                    return func(message.error, message)
                return func(Exception("Unknown error"), message)

            self.register_handler(
                topic_pattern=f"{topic_pattern}.error",
                callback=error_callback,
                priority=10,  # High priority for error handlers
            )
            return func

        return decorator

    # Fluent API
    def event(self, topic: str) -> EventBuilder:
        """Create event builder"""
        return EventBuilder(topic)

    def topic(self, name: str) -> "TopicBuilder":
        """Create topic builder"""
        return TopicBuilder(name, self)

    # Enhanced registration
    def register_handler(
        self,
        topic_pattern: str,
        callback: Callable,
        priority: int = 0,
        max_calls: Optional[int] = None,
        timeout: Optional[float] = None,
        exact_match: bool = False,
        error_handler: Optional[Callable] = None,
    ) -> str:
        """Register enhanced event handler"""

        pattern = EventPattern(topic_pattern, exact_match=exact_match)
        handler = EventHandler(
            handler_id=str(uuid4()),
            callback=callback,
            pattern=pattern,
            priority=priority,
            max_calls=max_calls,
            timeout=timeout,
            error_handler=error_handler,
        )

        with self.lock:
            self.handlers[topic_pattern].append(handler)
            self.handlers[topic_pattern].sort(key=lambda h: h.priority, reverse=True)
            self.stats["handlers_registered"] += 1

        return handler.handler_id

    # Batch operations
    def publish_batch(self, events: List[Dict[str, Any]]) -> List[str]:
        """Publish multiple events"""
        message_ids = []
        for event in events:
            message_id = self.publish(**event)
            message_ids.append(message_id)
        return message_ids

    def publish_delayed(self, topic: str, payload: Any, delay: float, **kwargs) -> str:
        """Publish event after delay"""

        def delayed_publish():
            time.sleep(delay)
            return self.publish(topic, payload, **kwargs)

        # Use threading for delay
        import threading

        thread = threading.Thread(target=delayed_publish, daemon=True)
        thread.start()
        return f"delayed_{uuid4()}"

    # Advanced patterns
    def request_response(
        self, topic: str, payload: Any, timeout: float = 10.0, **kwargs
    ) -> Any:
        """Request-response pattern with timeout"""
        reply_topic = f"reply_{uuid4()}"
        response_received = threading.Event()
        response_data = {}

        def reply_handler(message: Message):
            response_data["payload"] = message.payload
            response_received.set()

        # Register temporary reply handler
        reply_handler_id = self.register_handler(
            reply_topic, reply_handler, max_calls=1
        )

        try:
            # Publish request with reply-to
            self.publish(topic, payload, reply_to=reply_topic, **kwargs)

            # Wait for response
            if response_received.wait(timeout):
                return response_data.get("payload")
            else:
                raise TimeoutError(f"No response received within {timeout}s")

        finally:
            # Cleanup reply handler
            self.unregister_handler(reply_handler_id)

    def publish_and_wait(
        self, topic: str, payload: Any, wait_for: List[str], timeout: float = 10.0
    ) -> Dict[str, Any]:
        """Publish event and wait for specific responses"""
        correlation_id = str(uuid4())
        responses = {}
        received_topics = set()
        all_received = threading.Event()

        def response_handler(message: Message):
            if message.headers.get("correlation_id") == correlation_id:
                topic_name = message.topic
                responses[topic_name] = message.payload
                received_topics.add(topic_name)

                if len(received_topics) >= len(wait_for):
                    all_received.set()

        # Register handlers for expected responses
        handler_ids = []
        for response_topic in wait_for:
            handler_id = self.register_handler(response_topic, response_handler)
            handler_ids.append(handler_id)

        try:
            # Publish with correlation ID
            self.publish(topic, payload, headers={"correlation_id": correlation_id})

            # Wait for all responses
            if all_received.wait(timeout):
                return responses
            else:
                raise TimeoutError(f"Not all responses received within {timeout}s")

        finally:
            # Cleanup handlers
            for handler_id in handler_ids:
                self.unregister_handler(handler_id)

    def unregister_handler(self, handler_id: str) -> bool:
        """Unregister handler by ID"""
        with self.lock:
            for topic_pattern, handlers in self.handlers.items():
                self.handlers[topic_pattern] = [
                    h for h in handlers if h.handler_id != handler_id
                ]
            return True

    # Override publish to handle enhanced features
    def publish(
        self,
        topic: str,
        payload: Any = None,
        headers: Dict[str, Any] = None,
        sender: str = None,
        reply_to: str = None,
    ) -> str:
        """Enhanced publish with handler execution"""

        message = Message(
            topic=topic,
            payload=payload,
            headers=headers or {},
            sender=sender,
            reply_to=reply_to,
        )

        with self.lock:
            self.message_history.append(message)
            self.stats["events_published"] += 1

            # Find and execute matching handlers
            for topic_pattern, handlers in self.handlers.items():
                for handler in handlers:
                    if handler.should_handle(topic):
                        try:
                            handler(message)
                            self.stats["events_handled"] += 1
                        except Exception as e:
                            self.stats["errors"] += 1
                            # Publish error event
                            error_topic = f"{topic}.error"
                            error_message = Message(
                                topic=error_topic,
                                payload={"error": str(e), "original_message": message},
                                headers={"error_type": type(e).__name__},
                            )
                            # Don't recurse into error handling

        return message.id

    def get_stats(self) -> Dict[str, Any]:
        """Get enhanced statistics"""
        handler_stats = {}
        with self.lock:
            for topic_pattern, handlers in self.handlers.items():
                handler_stats[topic_pattern] = [
                    {
                        "handler_id": h.handler_id,
                        "call_count": h.call_count,
                        "last_called": h.last_called,
                        "priority": h.priority,
                    }
                    for h in handlers
                ]

        return {
            **self.stats,
            "active_handlers": sum(
                len(handlers) for handlers in self.handlers.values()
            ),
            "handler_details": handler_stats,
            "recent_messages": len(self.message_history),
        }


class TopicBuilder:
    """Builder for topic configuration"""

    def __init__(self, name: str, event_bus: EnhancedEventBus):
        self.name = name
        self.event_bus = event_bus
        self.description = ""
        self.schema = None
        self.tags = set()

    def with_description(self, description: str) -> "TopicBuilder":
        self.description = description
        return self

    def with_schema(self, schema: Dict[str, Any]) -> "TopicBuilder":
        self.schema = schema
        return self

    def with_tags(self, *tags: str) -> "TopicBuilder":
        self.tags.update(tags)
        return self

    def register(self):
        """Register the topic"""
        return self.event_bus.topic_registry.register_topic(
            name=self.name,
            description=self.description,
            schema=self.schema,
            tags=self.tags,
        )


# Global instance for convenience
_global_event_bus: Optional[EnhancedEventBus] = None


def get_global_event_bus() -> EnhancedEventBus:
    """Get global event bus instance"""
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EnhancedEventBus()
    return _global_event_bus


# Convenience decorators using global event bus
def on_event(topic_pattern: str, **kwargs):
    """Global event handler decorator"""
    bus = get_global_event_bus()
    return bus.on(topic_pattern, **kwargs)


def once_event(topic_pattern: str, **kwargs):
    """Global one-time event handler decorator"""
    bus = get_global_event_bus()
    return bus.once(topic_pattern, **kwargs)


def publish_event(topic: str, payload: Any = None, **kwargs) -> str:
    """Global event publishing function"""
    bus = get_global_event_bus()
    return bus.publish(topic, payload, **kwargs)


# Example usage
if __name__ == "__main__":

    # Create enhanced event bus
    bus = EnhancedEventBus()

    # Example 1: Decorator-based handlers
    @bus.on("user.*", priority=1)
    def handle_user_events(message: Message):
        print(f"🧑 User event: {message.topic} -> {message.payload}")
        return f"Processed user event: {message.topic}"

    @bus.once("system.startup")
    def handle_startup(message: Message):
        print(f"🚀 System startup: {message.payload}")

    @bus.error_handler("user.*")
    def handle_user_errors(error: Exception, message: Message):
        print(f"❌ User event error: {error}")

    # Example 2: Fluent event building
    event_id = (
        bus.event("user.login")
        .with_payload({"user_id": "123", "timestamp": time.time()})
        .with_headers(session_id="abc123")
        .with_sender("auth_service")
        .publish(bus)
    )

    print(f"Published event: {event_id}")

    # Example 3: Request-response pattern
    try:
        response = bus.request_response(
            "user.get_profile", {"user_id": "123"}, timeout=5.0
        )
        print(f"Response: {response}")
    except TimeoutError:
        print("No response received")

    # Example 4: Batch publishing
    batch_events = [
        {"topic": "user.login", "payload": {"user_id": "1"}},
        {"topic": "user.login", "payload": {"user_id": "2"}},
        {"topic": "system.metric", "payload": {"cpu": 75}},
    ]

    message_ids = bus.publish_batch(batch_events)
    print(f"Batch published: {len(message_ids)} events")

    # Show statistics
    stats = bus.get_stats()
    print(f"\n📊 Event Bus Stats:")
    print(f"  Events published: {stats['events_published']}")
    print(f"  Events handled: {stats['events_handled']}")
    print(f"  Active handlers: {stats['active_handlers']}")
