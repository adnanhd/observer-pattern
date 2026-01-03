#!/usr/bin/env python3
"""
Distributed Microservices - Application Example
Demonstrates inter-service communication using RPC and message queue.
"""

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from callpyback import (
    Executor,
    MessageQueue,
    RPCClient,
    RPCServer,
    TimingObserver,
    observe,
)


@dataclass
class ServiceRequest:
    request_id: str
    service_name: str
    method: str
    payload: Dict[str, Any]


@dataclass
class ServiceResponse:
    request_id: str
    service_name: str
    status: str
    data: Any = None
    error: Optional[str] = None


def main():
    # Shared message queue (in real world, this would be Redis/RabbitMQ)
    queue = MessageQueue()
    executor = Executor()
    timing = TimingObserver()

    # === User Service ===
    user_server = RPCServer(queue, executor, service_name="user")

    @user_server.register()
    def get_user(user_id: str) -> Dict[str, Any]:
        # Simulate DB lookup
        time.sleep(0.01)
        return {
            "user_id": user_id,
            "name": f"User {user_id}",
            "email": f"user{user_id}@example.com",
        }

    @user_server.register()
    def validate_user(user_id: str) -> bool:
        time.sleep(0.005)
        return user_id.startswith("U")

    # === Order Service ===
    order_server = RPCServer(queue, executor, service_name="order")

    @order_server.register()
    def create_order(user_id: str, items: list, total: float) -> Dict[str, Any]:
        time.sleep(0.02)
        order_id = f"ORD-{int(time.time() * 1000) % 10000}"
        return {
            "order_id": order_id,
            "user_id": user_id,
            "items": items,
            "total": total,
            "status": "created",
        }

    @order_server.register()
    def get_order(order_id: str) -> Dict[str, Any]:
        time.sleep(0.01)
        return {"order_id": order_id, "status": "processing"}

    # === Payment Service ===
    payment_server = RPCServer(queue, executor, service_name="payment")

    @payment_server.register()
    def process_payment(order_id: str, amount: float, method: str) -> Dict[str, Any]:
        time.sleep(0.03)
        return {
            "payment_id": f"PAY-{int(time.time() * 1000) % 10000}",
            "order_id": order_id,
            "amount": amount,
            "method": method,
            "status": "completed",
        }

    # Start all services
    user_server.serve(blocking=False)
    order_server.serve(blocking=False)
    payment_server.serve(blocking=False)
    time.sleep(0.1)

    # === API Gateway / Orchestrator ===
    user_client = RPCClient(queue, service_name="user", timeout=5.0)
    order_client = RPCClient(queue, service_name="order", timeout=5.0)
    payment_client = RPCClient(queue, service_name="payment", timeout=5.0)

    # Event logging
    @queue.on("service.log")
    def log_service_event(msg):
        event = msg.payload
        print(f"  [{event['service']}] {event['action']}: {event.get('details', '')}")

    @observe(timing)
    def checkout_flow(user_id: str, items: list, total: float):
        """Orchestrate checkout across services."""
        queue.publish("service.log", {"service": "gateway", "action": "checkout_start"})

        # 1. Validate user
        is_valid = user_client.validate_user(user_id)
        if not is_valid:
            raise ValueError(f"Invalid user: {user_id}")

        queue.publish(
            "service.log",
            {"service": "user", "action": "validated", "details": user_id},
        )

        # 2. Get user details
        user = user_client.get_user(user_id)
        queue.publish(
            "service.log",
            {"service": "user", "action": "fetched", "details": user["name"]},
        )

        # 3. Create order
        order = order_client.create_order(user_id, items, total)
        queue.publish(
            "service.log",
            {"service": "order", "action": "created", "details": order["order_id"]},
        )

        # 4. Process payment
        payment = payment_client.process_payment(
            order["order_id"], total, "credit_card"
        )
        queue.publish(
            "service.log",
            {
                "service": "payment",
                "action": "completed",
                "details": payment["payment_id"],
            },
        )

        return {
            "user": user,
            "order": order,
            "payment": payment,
        }

    print("=== Distributed Microservices Demo ===\n")

    # Execute checkout flow
    try:
        result = checkout_flow(
            user_id="U123",
            items=[{"sku": "ITEM-A", "qty": 2}, {"sku": "ITEM-B", "qty": 1}],
            total=149.99,
        )

        print(f"\nCheckout successful!")
        print(f"  Order: {result['order']['order_id']}")
        print(f"  Payment: {result['payment']['payment_id']}")
        print(f"  Total: ${result['order']['total']}")

    except Exception as e:
        print(f"Checkout failed: {e}")

    time.sleep(0.1)

    print(f"\nTiming: {timing.stats}")

    # Cleanup
    user_server.stop()
    order_server.stop()
    payment_server.stop()


if __name__ == "__main__":
    main()
