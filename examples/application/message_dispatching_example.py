#!/usr/bin/env python3
"""
Advanced Message Dispatching - Application Example
Demonstrates multiple inboxes/topics with multiple subscribers using MessageQueue.
"""

import random
import time
from dataclasses import dataclass

from callpyback import ExecutionMode, execution_session
from callpyback.execution import MessageQueue


@dataclass
class OrderMessage:
    order_id: str
    customer_id: str
    product_id: str
    quantity: int
    price: float
    priority: str = "normal"


@dataclass
class InventoryMessage:
    product_id: str
    current_stock: int
    reserved: int
    reorder_level: int


# Service classes that subscribe to different topics
class OrderProcessingService:
    """Handles order processing"""

    def __init__(self, service_id: str):
        self.service_id = service_id
        self.processed_orders = []

    def handle_new_order(self, message):
        """Handle new order messages"""
        order_data = message.payload
        processing_time = random.uniform(0.1, 0.3)
        time.sleep(processing_time)

        print(
            f"📦 [{self.service_id}] Processing order {order_data['order_id']} "
            f"for customer {order_data['customer_id']}"
        )

        self.processed_orders.append(order_data["order_id"])

        # Publish order processed event
        return {
            "order_id": order_data["order_id"],
            "processed_by": self.service_id,
            "processing_time": processing_time,
            "status": "processed",
        }

    def handle_priority_order(self, message):
        """Handle high-priority orders"""
        order_data = message.payload
        print(
            f"🚨 [{self.service_id}] PRIORITY ORDER: {order_data['order_id']} "
            f"(Customer: {order_data['customer_id']})"
        )

        # Process immediately with shorter time
        time.sleep(random.uniform(0.05, 0.1))
        return {"status": "priority_processed", "order_id": order_data["order_id"]}


class InventoryService:
    """Manages inventory updates"""

    def __init__(self, service_id: str):
        self.service_id = service_id
        self.inventory = {}

    def handle_inventory_update(self, message):
        """Handle inventory level updates"""
        inv_data = message.payload
        product_id = inv_data["product_id"]

        print(
            f"📊 [{self.service_id}] Inventory update for {product_id}: "
            f"Stock={inv_data['current_stock']}, Reserved={inv_data['reserved']}"
        )

        self.inventory[product_id] = inv_data

        # Check if reorder needed
        if inv_data["current_stock"] <= inv_data["reorder_level"]:
            print(
                f"⚠️ [{self.service_id}] REORDER ALERT: {product_id} "
                f"({inv_data['current_stock']} <= {inv_data['reorder_level']})"
            )

        return {"product_id": product_id, "updated_by": self.service_id}

    def handle_stock_check(self, message):
        """Handle stock level checks"""
        product_id = message.payload["product_id"]
        requested_qty = message.payload.get("requested_quantity", 1)

        current_stock = self.inventory.get(product_id, {}).get("current_stock", 0)
        available = current_stock >= requested_qty

        print(
            f"🔍 [{self.service_id}] Stock check {product_id}: "
            f"Requested={requested_qty}, Available={current_stock}, OK={available}"
        )

        return {
            "product_id": product_id,
            "requested_quantity": requested_qty,
            "available_stock": current_stock,
            "sufficient": available,
        }


class NotificationService:
    """Sends notifications based on various events"""

    def __init__(self, service_id: str):
        self.service_id = service_id
        self.notifications_sent = 0

    def handle_order_notification(self, message):
        """Send order-related notifications"""
        order_data = message.payload
        notification_type = message.topic.split(".")[-1]  # e.g., 'confirmed', 'shipped'

        print(
            f"📧 [{self.service_id}] Sending {notification_type} notification "
            f"for order {order_data['order_id']}"
        )

        # Simulate notification sending
        time.sleep(random.uniform(0.05, 0.15))
        self.notifications_sent += 1

        return {
            "notification_type": notification_type,
            "order_id": order_data["order_id"],
            "sent_by": self.service_id,
        }

    def handle_system_alert(self, message):
        """Handle system alerts and warnings"""
        alert_data = message.payload
        severity = alert_data.get("severity", "info")

        print(
            f"🚨 [{self.service_id}] SYSTEM ALERT ({severity}): {alert_data.get('message', 'Unknown')}"
        )

        return {"alert_processed": True, "severity": severity}


class AuditService:
    """Logs all activities for compliance"""

    def __init__(self, service_id: str):
        self.service_id = service_id
        self.audit_log = []

    def handle_audit_event(self, message):
        """Log any auditable event"""
        event_data = {
            "timestamp": time.time(),
            "topic": message.topic,
            "payload": message.payload,
            "message_id": message.id,
        }

        self.audit_log.append(event_data)
        print(f"📝 [{self.service_id}] Logged audit event: {message.topic}")

        return {"logged": True, "audit_count": len(self.audit_log)}


def setup_message_queue_system():
    """Setup the message queue with multiple services and subscriptions"""

    # Create message queue
    mq = MessageQueue(max_workers=6, enable_dead_letter=True)
    mq.start()

    # Create service instances
    order_service_1 = OrderProcessingService("OrderSvc-1")
    order_service_2 = OrderProcessingService("OrderSvc-2")
    inventory_service = InventoryService("InventorySvc")
    notification_service = NotificationService("NotificationSvc")
    audit_service = AuditService("AuditSvc")

    print("🔧 Setting up message queue subscriptions...")

    # Subscribe to order topics
    mq.subscribe("orders.new", order_service_1.handle_new_order)
    mq.subscribe("orders.new", order_service_2.handle_new_order)  # Load balancing
    mq.subscribe("orders.priority", order_service_1.handle_priority_order)
    mq.subscribe("orders.priority", order_service_2.handle_priority_order)

    # Subscribe to inventory topics
    mq.subscribe("inventory.update", inventory_service.handle_inventory_update)
    mq.subscribe("inventory.check", inventory_service.handle_stock_check)

    # Subscribe to notification topics (pattern-based)
    mq.subscribe(
        "notifications.order.confirmed", notification_service.handle_order_notification
    )
    mq.subscribe(
        "notifications.order.shipped", notification_service.handle_order_notification
    )
    mq.subscribe(
        "notifications.order.delivered", notification_service.handle_order_notification
    )
    mq.subscribe("system.alerts", notification_service.handle_system_alert)

    # Audit service subscribes to ALL topics (wildcard simulation)
    audit_topics = [
        "orders.new",
        "orders.priority",
        "inventory.update",
        "inventory.check",
        "notifications.order.confirmed",
        "notifications.order.shipped",
        "notifications.order.delivered",
        "system.alerts",
    ]

    for topic in audit_topics:
        mq.subscribe(topic, audit_service.handle_audit_event)

    return mq, {
        "order_services": [order_service_1, order_service_2],
        "inventory_service": inventory_service,
        "notification_service": notification_service,
        "audit_service": audit_service,
    }


def generate_order_messages(mq: MessageQueue, count: int):
    """Generate various order messages"""

    customer_ids = [f"CUST_{i:04d}" for i in range(1, 101)]
    product_ids = ["PROD_A", "PROD_B", "PROD_C", "PROD_D", "PROD_E"]

    for i in range(count):
        order_data = {
            "order_id": f"ORD_{int(time.time() * 1000) % 100000}_{i:03d}",
            "customer_id": random.choice(customer_ids),
            "product_id": random.choice(product_ids),
            "quantity": random.randint(1, 10),
            "price": round(random.uniform(10.0, 500.0), 2),
        }

        # 20% chance of priority order
        if random.random() < 0.2:
            order_data["priority"] = "high"
            mq.publish("orders.priority", order_data)
        else:
            mq.publish("orders.new", order_data)

        # Simulate related inventory check
        mq.publish(
            "inventory.check",
            {
                "product_id": order_data["product_id"],
                "requested_quantity": order_data["quantity"],
            },
        )

        time.sleep(random.uniform(0.01, 0.05))  # Realistic order spacing


def generate_inventory_messages(mq: MessageQueue, count: int):
    """Generate inventory update messages"""

    product_ids = ["PROD_A", "PROD_B", "PROD_C", "PROD_D", "PROD_E"]

    for i in range(count):
        product_id = random.choice(product_ids)

        inventory_data = {
            "product_id": product_id,
            "current_stock": random.randint(0, 100),
            "reserved": random.randint(0, 20),
            "reorder_level": random.randint(10, 30),
        }

        mq.publish("inventory.update", inventory_data)
        time.sleep(random.uniform(0.02, 0.08))


def generate_notification_messages(mq: MessageQueue, count: int):
    """Generate notification messages"""

    notification_types = ["confirmed", "shipped", "delivered"]

    for i in range(count):
        order_id = f"ORD_{random.randint(10000, 99999)}"
        notification_type = random.choice(notification_types)

        mq.publish(
            f"notifications.order.{notification_type}",
            {
                "order_id": order_id,
                "customer_email": f"customer{random.randint(1, 100)}@example.com",
                "timestamp": time.time(),
            },
        )

        time.sleep(random.uniform(0.03, 0.1))


def generate_system_alerts(mq: MessageQueue, count: int):
    """Generate system alert messages"""

    alert_types = [
        ("Database connection slow", "warning"),
        ("High memory usage detected", "warning"),
        ("Service timeout occurred", "error"),
        ("Backup completed successfully", "info"),
        ("Security scan completed", "info"),
    ]

    for i in range(count):
        message, severity = random.choice(alert_types)

        mq.publish(
            "system.alerts",
            {
                "message": message,
                "severity": severity,
                "component": f"component_{random.randint(1, 5)}",
                "timestamp": time.time(),
            },
        )

        time.sleep(random.uniform(0.1, 0.3))


def main():
    """Demo advanced message dispatching with multiple subscribers"""
    print("📨 Advanced Message Dispatching System")
    print("=" * 50)

    # Setup message queue system
    mq, services = setup_message_queue_system()

    try:
        with execution_session() as manager:
            # Configure for I/O intensive message processing
            manager.configure().max_threads(8).execution_mode(ExecutionMode.THREAD).apply()

            print("\n🚀 Starting parallel message generation...")

            # Generate different types of messages in parallel
            message_generators = [
                lambda: generate_order_messages(mq, 15),
                lambda: generate_inventory_messages(mq, 10),
                lambda: generate_notification_messages(mq, 12),
                lambda: generate_system_alerts(mq, 8),
            ]

            # Run all message generators in parallel
            start_time = time.time()
            manager.parallel(*message_generators)
            generation_time = time.time() - start_time

            print(f"📊 Message generation completed in {generation_time:.2f}s")

            # Allow time for message processing
            print("⏳ Allowing time for message processing...")
            time.sleep(2.0)

            # Show statistics
            stats = mq.get_stats()
            print(f"\n📈 Message Queue Statistics:")
            print(f"   Messages published: {stats['messages_published']}")
            print(f"   Messages processed: {stats['messages_processed']}")
            print(f"   Messages failed: {stats['messages_failed']}")
            print(f"   Active subscriptions: {stats['subscriptions_active']}")
            print(f"   Dead letter count: {stats['dead_letter_count']}")

            # Show service-specific stats
            print(f"\n📋 Service Statistics:")
            order_svc_1, order_svc_2 = services["order_services"]
            print(
                f"   Order Service 1: {len(order_svc_1.processed_orders)} orders processed"
            )
            print(
                f"   Order Service 2: {len(order_svc_2.processed_orders)} orders processed"
            )
            print(
                f"   Inventory Service: {len(services['inventory_service'].inventory)} products tracked"
            )
            print(
                f"   Notification Service: {services['notification_service'].notifications_sent} notifications sent"
            )
            print(
                f"   Audit Service: {len(services['audit_service'].audit_log)} events logged"
            )

            # Show queue lengths by topic
            if stats.get("queue_lengths"):
                print(f"\n📊 Queue Lengths by Topic:")
                for topic, length in stats["queue_lengths"].items():
                    if length > 0:
                        print(f"   {topic}: {length} pending messages")

            print(f"\n🎯 System demonstrates:")
            print(f"   ✅ Multiple subscribers per topic (load balancing)")
            print(f"   ✅ Topic-based message routing")
            print(f"   ✅ Cross-cutting concerns (audit)")
            print(f"   ✅ Pattern-based subscriptions")
            print(f"   ✅ Concurrent message processing")

    finally:
        # Cleanup
        print("\n🛑 Shutting down message queue...")
        mq.stop(timeout=2.0)


if __name__ == "__main__":
    main()
