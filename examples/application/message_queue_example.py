#!/usr/bin/env python3
"""
Uses enhanced EventBus with syntactic sugar
"""

import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

from enhanced_event_bus import EnhancedEventBus


class MessagePriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class OrderEvent:
    order_id: str
    user_id: str
    event_type: str
    data: Dict[str, Any]
    priority: MessagePriority = MessagePriority.NORMAL


@dataclass
class UserEvent:
    user_id: str
    event_type: str
    data: Dict[str, Any]
    timestamp: float


# Global event bus instance
event_bus = EnhancedEventBus()


# Event handlers using decorators
@event_bus.on("user.*", priority=2)
def handle_user_events(message):
    """Handle all user-related events"""
    payload = message.payload
    event_type = payload.get("event_type", "unknown")
    user_id = payload.get("user_id", "anonymous")

    print(f"👤 User Event: {event_type} for user {user_id}")

    # Process based on event type
    if event_type == "login":
        return {"action": "session_created", "user_id": user_id}
    elif event_type == "logout":
        return {"action": "session_ended", "user_id": user_id}
    elif event_type == "profile_update":
        return {"action": "profile_updated", "user_id": user_id}

    return {"action": "generic_user_event", "user_id": user_id}


@event_bus.on("order.*", priority=3)
def handle_order_events(message):
    """Handle all order-related events"""
    payload = message.payload
    order_id = payload.get("order_id", "unknown")
    event_type = payload.get("event_type", "unknown")

    print(f"🛒 Order Event: {event_type} for order {order_id}")

    # Simulate processing time
    time.sleep(random.uniform(0.01, 0.05))

    if event_type == "created":
        # Publish follow-up events
        event_bus.publish(
            "inventory.reserve",
            {"order_id": order_id, "items": payload.get("items", [])},
        )
        return {"action": "order_created", "order_id": order_id}

    elif event_type == "payment_received":
        event_bus.publish("order.fulfill", {"order_id": order_id, "priority": "high"})
        return {"action": "payment_processed", "order_id": order_id}

    elif event_type == "shipped":
        event_bus.publish(
            "notification.send",
            {
                "type": "shipping_notification",
                "order_id": order_id,
                "user_id": payload.get("user_id"),
            },
        )
        return {"action": "shipping_started", "order_id": order_id}

    return {"action": "generic_order_event", "order_id": order_id}


@event_bus.on("notification.*", priority=1)
def handle_notifications(message):
    """Handle notification events"""
    payload = message.payload
    notification_type = payload.get("type", "email")
    recipient = payload.get("user_id", "unknown")

    print(f"📬 Notification: {notification_type} to user {recipient}")

    # Simulate sending notification
    delivery_time = random.uniform(0.1, 0.3)
    time.sleep(delivery_time)

    # Occasional failures
    if random.random() < 0.1:  # 10% failure rate
        raise RuntimeError(f"Failed to send {notification_type} notification")

    return {
        "sent": True,
        "type": notification_type,
        "recipient": recipient,
        "delivery_time": delivery_time,
    }


@event_bus.on("inventory.*", priority=2)
def handle_inventory_events(message):
    """Handle inventory management"""
    payload = message.payload
    action = message.topic.split(".")[-1]

    print(f"📦 Inventory: {action}")

    if action == "reserve":
        order_id = payload.get("order_id")
        items = payload.get("items", [])

        # Simulate inventory check
        time.sleep(random.uniform(0.02, 0.1))

        # Occasionally out of stock
        if random.random() < 0.15:  # 15% out of stock
            event_bus.publish(
                "order.cancelled", {"order_id": order_id, "reason": "out_of_stock"}
            )
            return {"reserved": False, "reason": "out_of_stock"}

        return {"reserved": True, "order_id": order_id, "items": items}

    return {"action": action, "status": "processed"}


@event_bus.error_handler("*")
def handle_all_errors(error, message):
    """Global error handler"""
    print(f"❌ Error in {message.topic}: {error}")

    # Log error details
    error_log = {
        "topic": message.topic,
        "error": str(error),
        "timestamp": time.time(),
        "payload": message.payload,
    }

    # Could publish to error tracking system
    event_bus.publish("system.error", error_log)


@event_bus.once("system.startup")
def handle_system_startup(message):
    """Handle system startup - runs only once"""
    print("🚀 System starting up...")

    # Initialize system components
    startup_events = [
        {"topic": "cache.initialize", "payload": {"type": "redis"}},
        {"topic": "database.connect", "payload": {"pool_size": 10}},
        {"topic": "metrics.start", "payload": {"interval": 60}},
    ]

    event_bus.publish_batch(startup_events)
    print("✅ System startup complete")


class MessageQueueDemo:
    """Demonstration of message queue patterns"""

    def __init__(self):
        self.event_bus = event_bus
        self.processed_events = []

    def simulate_user_workflow(self, user_id: str) -> List[Dict]:
        """Simulate complete user workflow"""
        print(f"\n👤 Simulating workflow for user {user_id}")

        results = []

        # User login
        login_event = UserEvent(
            user_id=user_id,
            event_type="login",
            data={"ip_address": "192.168.1.100", "device": "mobile"},
            timestamp=time.time(),
        )

        message_id = self.event_bus.publish(
            "user.login",
            {"user_id": user_id, "event_type": "login", **login_event.data},
        )
        results.append({"event": "login", "message_id": message_id})

        # Profile update
        time.sleep(0.1)
        profile_event = UserEvent(
            user_id=user_id,
            event_type="profile_update",
            data={"fields": ["email", "phone"]},
            timestamp=time.time(),
        )

        message_id = self.event_bus.publish(
            "user.profile_update",
            {"user_id": user_id, "event_type": "profile_update", **profile_event.data},
        )
        results.append({"event": "profile_update", "message_id": message_id})

        return results

    def simulate_order_processing(self, order_id: str, user_id: str) -> List[Dict]:
        """Simulate order processing workflow"""
        print(f"\n🛒 Processing order {order_id}")

        results = []

        # Order creation
        order_event = OrderEvent(
            order_id=order_id,
            user_id=user_id,
            event_type="created",
            data={
                "items": [{"product_id": "123", "quantity": 2}],
                "total_amount": 99.99,
            },
        )

        message_id = self.event_bus.publish(
            "order.created",
            {
                "order_id": order_id,
                "user_id": user_id,
                "event_type": "created",
                **order_event.data,
            },
        )
        results.append({"stage": "created", "message_id": message_id})

        # Payment processing (after short delay)
        time.sleep(0.2)
        message_id = self.event_bus.publish(
            "order.payment_received",
            {
                "order_id": order_id,
                "user_id": user_id,
                "event_type": "payment_received",
                "payment_method": "credit_card",
            },
        )
        results.append({"stage": "payment", "message_id": message_id})

        # Shipping (after processing)
        time.sleep(0.3)
        message_id = self.event_bus.publish(
            "order.shipped",
            {
                "order_id": order_id,
                "user_id": user_id,
                "event_type": "shipped",
                "tracking_number": f"TRK{order_id}",
            },
        )
        results.append({"stage": "shipped", "message_id": message_id})

        return results

    def test_request_response_pattern(self) -> Dict[str, Any]:
        """Test request-response messaging pattern"""
        print(f"\n🔄 Testing request-response pattern")

        # Set up response handler
        @self.event_bus.once("user.profile.response")
        def profile_response_handler(message):
            return {
                "user_id": "123",
                "profile": {"name": "John Doe", "email": "john@example.com"},
                "last_login": time.time(),
            }

        try:
            # Make request and wait for response
            response = self.event_bus.request_response(
                "user.profile.get", {"user_id": "123"}, timeout=2.0
            )
            return {"status": "success", "response": response}

        except TimeoutError:
            return {"status": "timeout", "error": "No response received"}

    def run_demo(self):
        """Run complete message queue demonstration"""
        print("🚀 Starting Message Queue Demo")
        print("=" * 50)

        # Trigger system startup
        self.event_bus.publish("system.startup", {"version": "1.0.0"})

        # Simulate user workflows
        user_results = []
        for i in range(3):
            user_id = f"user_{i:03d}"
            results = self.simulate_user_workflow(user_id)
            user_results.extend(results)

        # Simulate order processing
        order_results = []
        for i in range(2):
            order_id = f"order_{i:03d}"
            user_id = f"user_{i:03d}"
            results = self.simulate_order_processing(order_id, user_id)
            order_results.extend(results)

        # Test request-response
        rr_result = self.test_request_response_pattern()

        # Wait for all async processing to complete
        time.sleep(1.0)

        # Show statistics
        stats = self.event_bus.get_stats()
        print(f"\n📊 Demo Results:")
        print(f"  Events published: {stats['events_published']}")
        print(f"  Events handled: {stats['events_handled']}")
        print(f"  Errors: {stats['errors']}")
        print(f"  Active handlers: {stats['active_handlers']}")
        print(f"  User events: {len(user_results)}")
        print(f"  Order events: {len(order_results)}")
        print(f"  Request-response: {rr_result['status']}")

        return {
            "user_results": user_results,
            "order_results": order_results,
            "request_response": rr_result,
            "stats": stats,
        }


def main():
    """Run the message queue demo"""
    demo = MessageQueueDemo()

    try:
        results = demo.run_demo()
        print("\n✅ Message Queue Demo completed successfully!")
        return results

    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        raise


if __name__ == "__main__":
    main()
