#!/usr/bin/env python3
"""
Level 3 Execution Manager - Comprehensive Test
Tests all global functions: run_parallel, emit_event, on_event
"""

import time

from callpyback import ExecutionMode, emit_event, on_event, execution_session, run_parallel


# Global event handlers using decorators
@on_event("task.completed")
def handle_task_completion(message):
    print(f"✅ Task completed: {message.payload}")


@on_event("user.*")  # Pattern matching
def handle_user_events(message):
    print(f"👤 User event {message.topic}: {message.payload}")


@on_event("system.error", priority=None, once=False)
def handle_system_errors(message):
    print(f"❌ System error: {message.payload}")


def cpu_task(n: int) -> int:
    """Simulate CPU work"""
    return sum(range(n))


def io_task(delay: float) -> str:
    """Simulate I/O work"""
    time.sleep(delay)
    return f"IO completed after {delay}s"


def main():
    print("🚀 CallPyBack Level 3 Execution Manager - Comprehensive Test")
    print("=" * 60)

    # Test 1: Context manager (this was working)
    print("\n1️⃣ Testing Context Manager:")
    with execution_session() as manager:
        manager.configure().max_threads(4).execution_mode(ExecutionMode.HYBRID).apply()

        results = manager.parallel(
            lambda: cpu_task(1000),
            lambda: io_task(0.1),
            lambda: cpu_task(2000),
            lambda: io_task(0.2),
        )

        print(f"   Results: {results}")

        # Test events within context
        manager.emit("task.completed", {"task_id": "context_task", "result": "success"})

        metrics = manager.get_metrics()
        print(f"   Tasks completed: {metrics['tasks_completed']}")

    # Give time for events to process
    time.sleep(0.1)

    # Test 2: Global run_parallel function
    print("\n2️⃣ Testing Global run_parallel:")
    try:
        global_results = run_parallel(
            lambda: cpu_task(500), lambda: io_task(0.05), lambda: cpu_task(300)
        )
        print(f"   Global parallel results: {global_results}")
    except Exception as e:
        print(f"   ❌ Global run_parallel failed: {e}")

    # Test 3: Global emit_event function
    print("\n3️⃣ Testing Global emit_event:")
    try:
        # Test basic event
        event_id1 = emit_event(
            "task.completed", {"task_id": "global_task_1", "status": "done"}
        )
        print(f"   Emitted event 1: {event_id1}")

        # Test pattern-matched events
        event_id2 = emit_event(
            "user.login", {"user_id": "john_doe", "timestamp": time.time()}
        )
        print(f"   Emitted event 2: {event_id2}")

        event_id3 = emit_event(
            "user.logout", {"user_id": "john_doe", "session_duration": 3600}
        )
        print(f"   Emitted event 3: {event_id3}")

        # Test error event
        event_id4 = emit_event(
            "system.error", {"error_code": 500, "message": "Test error"}
        )
        print(f"   Emitted event 4: {event_id4}")

    except Exception as e:
        print(f"   ❌ Global emit_event failed: {e}")

    # Give time for events to process
    time.sleep(0.2)

    # Test 4: Combined usage - parallel execution + events
    print("\n4️⃣ Testing Combined Usage (Parallel + Events):")
    try:
        # Function that emits events
        def task_with_events(task_id: str) -> str:
            emit_event("task.started", {"task_id": task_id})

            # Do some work
            result = cpu_task(200)

            emit_event("task.completed", {"task_id": task_id, "result": result})
            return f"Task {task_id} completed with result {result}"

        # Run multiple tasks in parallel, each emitting events
        combined_results = run_parallel(
            lambda: task_with_events("A"),
            lambda: task_with_events("B"),
            lambda: task_with_events("C"),
        )

        print(f"   Combined results: {combined_results}")

    except Exception as e:
        print(f"   ❌ Combined usage failed: {e}")

    # Give time for final events to process
    time.sleep(0.2)

    # Test 5: Event registration after emission
    print("\n5️⃣ Testing Late Event Registration:")
    try:
        # Emit events first
        emit_event(
            "late.test", {"message": "This was emitted before handler registration"}
        )

        # Register handler after emission (should not receive above event)
        @on_event("late.test")
        def handle_late_events(message):
            print(f"🕐 Late handler received: {message.payload}")

        # Emit again (should receive this one)
        emit_event(
            "late.test", {"message": "This was emitted after handler registration"}
        )

        time.sleep(0.1)

    except Exception as e:
        print(f"   ❌ Late registration test failed: {e}")

    # Test 6: Performance test
    print("\n6️⃣ Performance Test:")
    try:
        start_time = time.time()

        # Run many small tasks
        many_results = run_parallel(*[lambda i=i: i * 2 for i in range(10)])

        end_time = time.time()

        print(f"   Processed {len(many_results)} tasks in {end_time - start_time:.3f}s")
        print(f"   Results: {many_results}")

    except Exception as e:
        print(f"   ❌ Performance test failed: {e}")

    print("\n🎯 Test Summary:")
    print("   - Context manager: ✅ (known working)")
    print("   - Global run_parallel: Check output above")
    print("   - Global emit_event: Check output above")
    print("   - Event handlers: Check if events were received")
    print("   - Combined usage: Check output above")

    print("\n✅ Comprehensive test completed!")


if __name__ == "__main__":
    main()
