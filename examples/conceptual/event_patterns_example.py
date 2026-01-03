#!/usr/bin/env python3
"""
Event Patterns - Conceptual Example
Demonstrates various event patterns using message queue.
"""

import time

from callpyback import MessageQueue, TimingObserver, observe


def main():
    queue = MessageQueue()

    # Pattern-based event handlers
    @queue.on("user.*")
    def handle_user_events(msg):
        print(f"User event: {msg.topic} -> {msg.payload}")

    @queue.on("system.*")
    def handle_system_events(msg):
        print(f"System event: {msg.topic} -> {msg.payload}")

    @queue.on("order.created")
    def handle_order_created(msg):
        order = msg.payload
        print(f"Order created: {order['id']} - ${order['total']}")
        # Trigger follow-up events
        queue.publish(
            "notification.send", {"type": "order_confirmation", "order_id": order["id"]}
        )

    @queue.on("notification.*")
    def handle_notifications(msg):
        print(f"Notification: {msg.topic} -> {msg.payload}")

    # Publish various events
    print("=== User Events ===")
    queue.publish("user.login", {"user_id": "123", "timestamp": time.time()})
    queue.publish("user.logout", {"user_id": "123", "timestamp": time.time()})
    queue.publish("user.profile_update", {"user_id": "123", "field": "email"})

    time.sleep(0.1)  # Allow handlers to process

    print("\n=== System Events ===")
    queue.publish("system.startup", {"version": "1.0.0"})
    queue.publish("system.health_check", {"status": "healthy"})

    time.sleep(0.1)

    print("\n=== Order Flow ===")
    queue.publish("order.created", {"id": "ORD-001", "total": 99.99, "items": 3})

    time.sleep(0.1)

    # Request-reply pattern
    print("\n=== Request-Reply Pattern ===")

    @queue.on("calc.square")
    def handle_square(msg):
        n = msg.payload["n"]
        if msg.reply_to:
            queue.publish(msg.reply_to, {"result": n * n})

    # Subscribe to calc.square first
    queue.subscribe("calc.square", handle_square)

    # Make a request (note: this is simplified, real request-reply uses queue.request())
    queue.publish("calc.square", {"n": 7})

    time.sleep(0.1)
    print("Done!")


if __name__ == "__main__":
    main()
