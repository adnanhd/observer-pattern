#!/usr/bin/env python3
"""
Core message queue and event bus implementation.
Provides publish-subscribe patterns with CallPyBack integration.
"""

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from callpyback.plugins.core.message_queue import Message, MessageQueue

logger = logging.getLogger(__name__)


@dataclass
class EventPattern:
    """Event pattern matching for topic subscriptions."""

    pattern: str
    exact_match: bool = False
    case_sensitive: bool = True

    def matches(self, topic: str) -> bool:
        """Check if topic matches this pattern."""
        if self.exact_match:
            return (
                topic == self.pattern
                if self.case_sensitive
                else topic.lower() == self.pattern.lower()
            )

        pattern = self.pattern if self.case_sensitive else self.pattern.lower()
        topic_check = topic if self.case_sensitive else topic.lower()

        if "*" in pattern:
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
    """Event handler with metadata and execution tracking."""

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
        """Determine if this handler should process the given topic."""
        if self.max_calls and self.call_count >= self.max_calls:
            return False
        return self.pattern.matches(topic)

    def __call__(self, message) -> Any:
        """Execute the handler callback."""
        self.call_count += 1
        self.last_called = time.time()

        try:
            return self.callback(message)
        except Exception as e:
            if self.error_handler:
                return self.error_handler(e, message)
            raise


class EventBus(MessageQueue):
    """
    Enhanced event bus with advanced pattern matching and handler management.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.event_handlers: Dict[str, List[Callable]] = defaultdict(list)
        self.enhanced_handlers: Dict[str, List[EventHandler]] = defaultdict(list)
        self.enhanced_stats = {
            "events_published": 0,
            "events_handled": 0,
            "handlers_registered": 0,
            "errors": 0,
        }

    def on(
        self,
        event: str,
        handler: Optional[Callable] = None,
        priority: int = 0,
        max_calls: Optional[int] = None,
        timeout: Optional[float] = None,
        exact_match: bool = False,
    ):
        """Enhanced decorator for pattern-based event handlers."""

        def decorator(func: Callable) -> Callable:
            pattern = EventPattern(event, exact_match=exact_match)
            event_handler = EventHandler(
                handler_id=str(uuid4()),
                callback=func,
                pattern=pattern,
                priority=priority,
                max_calls=max_calls,
                timeout=timeout,
            )

            with self.lock:
                self.enhanced_handlers[event].append(event_handler)
                self.enhanced_handlers[event].sort(
                    key=lambda h: h.priority, reverse=True
                )
                self.enhanced_stats["handlers_registered"] += 1

            # Also register with base MessageQueue for compatibility
            self.subscribe(event, func)

            return func

        if handler is None:
            return decorator
        else:
            return decorator(handler)

    def once(self, event: str, handler: Optional[Callable] = None, priority: int = 0):
        """Decorator for single-execution event handlers."""
        if handler is None:
            return self.on(event, priority=priority, max_calls=1)
        else:
            return self.on(event, handler, priority=priority, max_calls=1)

    def emit(self, event: str, *args, **kwargs):
        """Emit event with arguments."""
        self.publish(event, {"args": args, "kwargs": kwargs})

    def error_handler(self, event_pattern: str = "*"):
        """Decorator for error event handlers."""

        def decorator(func: Callable) -> Callable:
            def error_callback(message):
                if hasattr(message, "error"):
                    return func(message.error, message)
                return func(Exception("Unknown error"), message)

            return self.on(f"{event_pattern}.error", error_callback, priority=10)

        return decorator

    def request_response(
        self,
        topic: str,
        payload: Any,
        timeout: float = 10.0,
        headers: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Publish request and wait for response."""
        reply_topic = f"reply_{uuid4()}"
        correlation_id = str(uuid4())

        response_received = threading.Event()
        response_data = {}

        def reply_handler(message):
            response_data["payload"] = message.payload
            response_received.set()

        reply_handler_id = self.subscribe(reply_topic, reply_handler)

        try:
            request_headers = headers or {}
            request_headers.update(
                {"reply_to": reply_topic, "correlation_id": correlation_id}
            )

            self.publish(topic, payload, headers=request_headers, reply_to=reply_topic)

            if response_received.wait(timeout):
                return response_data.get("payload")
            else:
                raise TimeoutError(f"No response received within {timeout}s")

        finally:
            self.unsubscribe(reply_handler_id)

    def publish_batch(self, events: List[Dict[str, Any]]) -> List[str]:
        """Publish multiple events in batch."""
        message_ids = []
        for event in events:
            message_id = self.publish(**event)
            message_ids.append(message_id)
        return message_ids

    def publish(
        self,
        topic: str,
        payload: Any = None,
        headers: Optional[Dict[str, Any]] = None,
        sender: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> str:
        """Enhanced publish that works with both old and new handlers."""

        # Call parent publish for base functionality
        message_id = super().publish(topic, payload, headers, sender, reply_to)

        # Handle enhanced pattern-based handlers
        with self.lock:
            self.enhanced_stats["events_published"] += 1

            for pattern_str, handlers in self.enhanced_handlers.items():
                for handler in handlers:
                    if handler.should_handle(topic):
                        try:
                            # Create message object for handler
                            message = Message(
                                id=message_id,
                                topic=topic,
                                payload=payload,
                                headers=headers or {},
                                sender=sender,
                                reply_to=reply_to,
                            )
                            handler(message)
                            self.enhanced_stats["events_handled"] += 1
                        except Exception as e:
                            logger.error(f"Error handling message: {e}")
                            self.enhanced_stats["errors"] += 1

        return message_id

    def get_stats(self) -> Dict[str, Any]:
        """Get enhanced statistics including both base and enhanced handlers."""
        base_stats = super().get_stats()

        with self.lock:
            handler_stats = {}
            for pattern, handlers in self.enhanced_handlers.items():
                handler_stats[pattern] = [
                    {
                        "handler_id": h.handler_id,
                        "call_count": h.call_count,
                        "last_called": h.last_called,
                        "priority": h.priority,
                    }
                    for h in handlers
                ]

            enhanced_info = {
                **self.enhanced_stats,
                "active_enhanced_handlers": sum(
                    len(handlers) for handlers in self.enhanced_handlers.values()
                ),
                "handler_details": handler_stats,
            }

            return {**base_stats, **enhanced_info}
