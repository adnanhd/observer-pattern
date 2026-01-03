#!/usr/bin/env python3
"""
Event Patterns - Conceptual Example
Demonstrates event-driven patterns with the unified execution API.
"""

import random
import time

from callpyback import emit_event, on_event, execution_session, run_parallel


# Pattern-based event handlers
@on_event("user.*")
def handle_user_events(message):
    """Handle all user-related events"""
    action = message.topic.split(".")[-1]
    user = message.payload.get("user_id", "unknown")
    print(f"👤 User {action}: {user}")


@on_event("system.alert.*")
def handle_system_alerts(message):
    """Handle system alerts with different severity"""
    severity = message.topic.split(".")[-1]
    alert_type = message.payload.get("type", "generic")
    print(f"🚨 {severity.upper()} ALERT: {alert_type}")


@on_event("*.completed")
def handle_completions(message):
    """Handle any completion event"""
    task_type = message.topic.split(".")[0]
    print(f"✅ {task_type.capitalize()} completed successfully")


@on_event("workflow.step.*")
def track_workflow_progress(message):
    """Track workflow progress"""
    step = message.topic.split(".")[-1]
    workflow_id = message.payload.get("workflow_id", "unknown")
    print(f"🔄 Workflow {workflow_id} - Step: {step}")


def simulate_user_activity(user_id: str) -> str:
    """Simulate user activity with events"""

    # User login
    emit_event(
        "user.login",
        {
            "user_id": user_id,
            "timestamp": time.time(),
            "ip_address": f"192.168.1.{random.randint(1, 255)}",
        },
    )

    # Random user actions
    actions = ["browse", "purchase", "comment", "share"]
    for _ in range(random.randint(1, 3)):
        action = random.choice(actions)
        emit_event(
            f"user.{action}",
            {"user_id": user_id, "item_id": f"item_{random.randint(1, 100)}"},
        )
        time.sleep(0.1)

    # User logout
    emit_event(
        "user.logout",
        {"user_id": user_id, "session_duration": random.randint(300, 3600)},
    )

    return f"User {user_id} activity completed"


def simulate_workflow(workflow_id: str) -> str:
    """Simulate a multi-step workflow"""

    steps = ["initialize", "validate", "process", "finalize"]

    for step in steps:
        emit_event(
            f"workflow.step.{step}",
            {"workflow_id": workflow_id, "timestamp": time.time()},
        )

        # Simulate step processing time
        time.sleep(random.uniform(0.05, 0.2))

        # Random chance of alert during processing
        if step == "process" and random.random() < 0.3:
            severity = random.choice(["warning", "critical"])
            emit_event(
                f"system.alert.{severity}",
                {"type": "processing_delay", "workflow_id": workflow_id},
            )

    # Workflow completion
    emit_event(
        "workflow.completed",
        {"workflow_id": workflow_id, "total_time": random.uniform(1.0, 5.0)},
    )

    return f"Workflow {workflow_id} completed"


def main():
    """Demo event patterns with parallel execution"""
    print("📡 Event Patterns with Unified Execution API")
    print("=" * 50)

    # Test 1: Global functions without context manager
    print("\n1️⃣ Testing Global Functions:")

    # Emit some standalone events
    emit_event("system.startup", {"version": "1.0.0", "mode": "production"})
    emit_event(
        "user.admin.login",
        {"user_id": "admin", "permissions": ["read", "write", "delete"]},
    )

    # Run parallel tasks using global function
    user_results = run_parallel(
        lambda: simulate_user_activity("user_001"),
        lambda: simulate_user_activity("user_002"),
        lambda: simulate_user_activity("user_003"),
    )
    print(f"   Parallel user results: {len(user_results)} completed")

    time.sleep(0.2)  # Let events process

    # Test 2: Context manager with configuration
    print("\n2️⃣ Testing Context Manager:")

    with execution_session() as manager:
        # Configure the manager
        manager.configure().max_processes(3).enable_hybrid().apply()

        # Run workflows in parallel
        workflow_results = manager.map_parallel(
            simulate_workflow, [f"workflow_{i:03d}" for i in range(4)]
        )

        print(f"   Workflow results: {len(workflow_results)} completed")

        # Emit final events
        manager.emit("system.shutdown", {"reason": "demo_completed"})

        # Show metrics
        metrics = manager.get_metrics()
        print("\n📊 Manager Metrics:")
        print(f"   Events published: {metrics['events_published']}")
        print(f"   Tasks completed: {metrics['tasks_completed']}")

    time.sleep(0.1)  # Final event processing
    print("\n✅ Event patterns demo completed!")
    print(manager.get_executor_mode())


if __name__ == "__main__":
    main()
