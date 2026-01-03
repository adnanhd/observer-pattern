#!/usr/bin/env python3
"""
Message Dispatching - Application Example
Demonstrates message routing and dispatching patterns.
"""

import time
from dataclasses import dataclass
from typing import Any, Dict, List

from callpyback import MessageQueue, MetricsObserver, TimingObserver, observe


@dataclass
class OrderMessage:
    order_id: str
    customer_id: str
    items: List[Dict[str, Any]]
    total: float
    priority: str = "normal"


def main():
    queue = MessageQueue()
    timing = TimingObserver()
    metrics = MetricsObserver()

    processed_orders: List[str] = []
    notifications_sent: List[str] = []

    # Order processing handlers
    @queue.on("order.created")
    def handle_order_created(msg):
        order = msg.payload
        print(f"Order received: {order['order_id']} (${order['total']:.2f})")

        # Route based on priority
        if order.get("priority") == "high":
            queue.publish("order.priority", order)
        else:
            queue.publish("order.standard", order)

    @queue.on("order.priority")
    def handle_priority_order(msg):
        order = msg.payload
        print(f"  [PRIORITY] Processing: {order['order_id']}")
        time.sleep(0.01)  # Fast processing
        queue.publish("order.processed", order)

    @queue.on("order.standard")
    def handle_standard_order(msg):
        order = msg.payload
        print(f"  [STANDARD] Processing: {order['order_id']}")
        time.sleep(0.02)  # Normal processing
        queue.publish("order.processed", order)

    @queue.on("order.processed")
    def handle_order_processed(msg):
        order = msg.payload
        processed_orders.append(order["order_id"])

        # Trigger notifications
        queue.publish(
            "notification.send",
            {
                "type": "order_confirmation",
                "customer_id": order["customer_id"],
                "order_id": order["order_id"],
            },
        )

        # Trigger inventory update
        queue.publish("inventory.update", {"items": order["items"]})

    @queue.on("notification.send")
    def handle_notification(msg):
        notif = msg.payload
        notifications_sent.append(notif["order_id"])
        print(f"  Notification sent to customer {notif['customer_id']}")

    @queue.on("inventory.update")
    def handle_inventory(msg):
        items = msg.payload["items"]
        print(f"  Inventory updated: {len(items)} items")

    # Create orders
    orders = [
        OrderMessage("ORD-001", "CUST-A", [{"sku": "ABC", "qty": 2}], 99.99, "high"),
        OrderMessage("ORD-002", "CUST-B", [{"sku": "XYZ", "qty": 1}], 49.99, "normal"),
        OrderMessage("ORD-003", "CUST-C", [{"sku": "DEF", "qty": 3}], 149.99, "high"),
        OrderMessage("ORD-004", "CUST-D", [{"sku": "GHI", "qty": 1}], 29.99, "normal"),
    ]

    print("=== Message Dispatching Demo ===\n")

    # Process orders
    for order in orders:
        queue.publish("order.created", order.__dict__)
        time.sleep(0.05)  # Simulate arrival

    time.sleep(0.2)  # Allow processing

    print(f"\n=== Summary ===")
    print(f"Orders processed: {len(processed_orders)}")
    print(f"Notifications sent: {len(notifications_sent)}")


if __name__ == "__main__":
    main()
