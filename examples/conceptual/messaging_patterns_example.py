#!/usr/bin/env python3
"""
Messaging Patterns - Conceptual Example  
Demonstrates request-response and pub-sub messaging patterns.
"""

import random
import time

from callpyback import ExecutionMode, emit_event, on_event, plugin_session


# Service response handlers
@on_event("service.*.request")
def handle_service_requests(message):
    """Handle incoming service requests"""
    service = message.topic.split(".")[1]
    request_id = message.payload.get("request_id", "unknown")
    print(f"📥 {service} service received request: {request_id}")


@on_event("service.*.response")
def handle_service_responses(message):
    """Handle service responses"""
    service = message.topic.split(".")[1]
    request_id = message.payload.get("request_id", "unknown")
    status = message.payload.get("status", "unknown")
    print(f"📤 {service} service responded: {request_id} - {status}")


@on_event("monitor.*")
def handle_monitoring_events(message):
    """Monitor system events"""
    event_type = message.topic.split(".")[1]
    print(f"📊 Monitor: {event_type} - {message.payload}")


def simulate_auth_service(request_id: str) -> dict:
    """Simulate authentication service"""
    emit_event(
        "service.auth.request",
        {
            "request_id": request_id,
            "user_id": f"user_{random.randint(1, 100)}",
            "timestamp": time.time(),
        },
    )

    # Simulate processing
    time.sleep(random.uniform(0.1, 0.3))

    # Random success/failure
    success = random.random() > 0.2
    status = "success" if success else "unauthorized"

    result = {
        "request_id": request_id,
        "status": status,
        "token": f"token_{request_id}" if success else None,
        "expires_in": 3600 if success else 0,
    }

    emit_event("service.auth.response", result)

    # Emit monitoring events
    emit_event("monitor.auth_attempt", {"success": success, "request_id": request_id})

    return result


def simulate_data_service(request_id: str) -> dict:
    """Simulate data retrieval service"""
    emit_event(
        "service.data.request",
        {
            "request_id": request_id,
            "query": f"SELECT * FROM table WHERE id = {random.randint(1, 1000)}",
            "timestamp": time.time(),
        },
    )

    # Simulate database query
    time.sleep(random.uniform(0.05, 0.25))

    # Random data size
    record_count = random.randint(0, 50)

    result = {
        "request_id": request_id,
        "status": "success" if record_count > 0 else "not_found",
        "record_count": record_count,
        "data_size": record_count * random.randint(100, 500),
    }

    emit_event("service.data.response", result)

    # Emit performance monitoring
    emit_event(
        "monitor.query_performance", {"records": record_count, "request_id": request_id}
    )

    return result


def simulate_notification_service(request_id: str) -> dict:
    """Simulate notification service"""
    emit_event(
        "service.notification.request",
        {
            "request_id": request_id,
            "recipient": f"user_{random.randint(1, 100)}@example.com",
            "type": random.choice(["email", "sms", "push"]),
        },
    )

    # Simulate sending
    time.sleep(random.uniform(0.2, 0.4))

    # Usually successful
    success = random.random() > 0.1

    result = {
        "request_id": request_id,
        "status": "sent" if success else "failed",
        "delivery_time": time.time(),
        "attempts": 1 if success else random.randint(1, 3),
    }

    emit_event("service.notification.response", result)

    emit_event(
        "monitor.notification_sent", {"success": success, "request_id": request_id}
    )

    return result


def main():
    """Demonstrate messaging patterns"""
    print("📡 Messaging Patterns Demo")
    print("=" * 40)

    with plugin_session() as manager:
        # Configure for I/O intensive microservices
        manager.configure().max_threads(6).execution_mode(ExecutionMode.THREAD).apply()

        print("\n🔄 Starting microservices simulation...")

        # Generate request IDs
        request_ids = [f"req_{i:03d}" for i in range(8)]

        # Run multiple services concurrently
        print("🚀 Processing authentication requests...")
        auth_results = manager.map_parallel(simulate_auth_service, request_ids[:4])

        print("\n🗄️ Processing data requests...")
        data_results = manager.map_parallel(simulate_data_service, request_ids[2:6])

        print("\n📧 Processing notification requests...")
        notification_results = manager.map_parallel(
            simulate_notification_service, request_ids[4:]
        )

        # Aggregate results
        all_results = {
            "auth": auth_results,
            "data": data_results,
            "notifications": notification_results,
        }

        print(f"\n📊 Service Results Summary:")
        for service, results in all_results.items():
            successful = sum(
                1 for r in results if r.get("status") in ["success", "sent"]
            )
            total = len(results)
            success_rate = (successful / total * 100) if total > 0 else 0
            print(f"   {service}: {successful}/{total} ({success_rate:.1f}% success)")

        # Emit system-wide events
        emit_event(
            "monitor.system_status",
            {
                "total_requests": len(request_ids),
                "services_active": 3,
                "timestamp": time.time(),
            },
        )

        # Show performance metrics
        metrics = manager.get_metrics()
        print(f"\n📈 System Metrics:")
        print(f"   Events published: {metrics['events_published']}")
        print(f"   Tasks completed: {metrics['tasks_completed']}")
        print(f"   Health: {manager.health_check()}")

    time.sleep(0.1)  # Let final events process
    print("\n✅ Messaging patterns demo completed!")


if __name__ == "__main__":
    main()
