#!/usr/bin/env python3
"""
Basic Executor Usage Examples

This example demonstrates the fundamental usage patterns for all executor types
in CallPyBack. Each executor provides the same interface but with different
execution strategies.
"""

import time

from callpyback import (
    HybridExecutor,
    ProcessExecutor,
    SequentialExecutor,
    TaskStatus,
    ThreadExecutor,
)


def simple_computation(x: int, y: int) -> int:
    """A simple computation function."""
    return x + y


def slow_io_operation(url: str) -> str:
    """Simulate an I/O operation."""
    time.sleep(0.1)  # Simulate network delay
    return f"Fetched: {url}"


def cpu_intensive_task(n: int) -> int:
    return sum(i**2 for i in range(n))


def main():
    print("=" * 60)
    print("CallPyBack Executors - Basic Usage Examples")
    print("=" * 60)

    # Example 1: Sequential Executor
    print("\n1. Sequential Executor")
    print("-" * 40)

    with SequentialExecutor() as executor:
        # Submit task
        task_id = executor.submit(simple_computation, 10, 20)
        print(f"   Submitted task: {task_id[:8]}...")

        # Get result
        result = executor.get_result(task_id)
        print(f"   Result: {result.value}")
        print(f"   Status: {result.status.value}")
        print(f"   Execution time: {result.execution_time:.4f}s")

    # Example 2: Thread Executor
    print("\n2. Thread Executor (Concurrent I/O)")
    print("-" * 40)

    urls = [
        "https://api.example.com/users",
        "https://api.example.com/posts",
        "https://api.example.com/comments",
        "https://api.example.com/albums",
    ]

    with ThreadExecutor(max_workers=4) as executor:
        start_time = time.time()

        # Submit multiple I/O tasks
        task_ids = [executor.submit(slow_io_operation, url) for url in urls]
        print(f"   Submitted {len(task_ids)} tasks")

        # Collect results
        results = []
        for task_id in task_ids:
            result = executor.get_result(task_id, timeout=5.0)
            results.append(result.value)

        elapsed = time.time() - start_time
        print(f"   All tasks completed in {elapsed:.3f}s")
        print(f"   (Sequential would take ~{len(urls) * 0.1:.1f}s)")

    # Example 3: Process Executor
    print("\n3. Process Executor (Parallel CPU)")
    print("-" * 40)

    # Note: For ProcessExecutor, functions must be defined at module level
    # (they need to be picklable)

    with ProcessExecutor(max_workers=4) as executor:
        start_time = time.time()

        # Submit CPU-intensive tasks
        task_ids = [executor.submit(cpu_intensive_task, 100000) for _ in range(4)]
        print(f"   Submitted {len(task_ids)} CPU tasks")

        # Collect results
        for i, task_id in enumerate(task_ids):
            result = executor.get_result(task_id, timeout=30.0)
            print(f"   Task {i + 1}: {result.value:,}")

        elapsed = time.time() - start_time
        print(f"   Completed in {elapsed:.3f}s")

    # Example 4: Hybrid Executor
    print("\n4. Hybrid Executor (Smart Routing)")
    print("-" * 40)

    with HybridExecutor(max_threads=4, max_processes=2) as executor:
        # I/O task (routed to thread)
        io_task = executor.submit(slow_io_operation, "https://example.com")

        # CPU task (routed to process)
        cpu_task = executor.submit(cpu_intensive_task, 50000)

        io_result = executor.get_result(io_task, timeout=5.0)
        cpu_result = executor.get_result(cpu_task, timeout=30.0)

        print(f"   I/O result: {io_result.value[:30]}...")
        print(f"   CPU result: {cpu_result.value:,}")

        # View routing statistics
        stats = executor.get_detailed_stats()
        print(f"   Thread tasks: {stats['routing']['thread_tasks']}")
        print(f"   Process tasks: {stats['routing']['process_tasks']}")

    # Example 5: Task Features
    print("\n5. Task Features")
    print("-" * 40)

    with ThreadExecutor(max_workers=2) as executor:
        # Priority-based scheduling
        low_priority = executor.submit(simple_computation, 1, 2, priority=1)
        high_priority = executor.submit(simple_computation, 3, 4, priority=10)

        # With metadata
        with_meta = executor.submit(
            simple_computation, 5, 6, metadata={"user": "admin", "request_id": "abc123"}
            metadata={"user": "admin", "request_id": "abc123"}
        )

        # Get results
        for task_id in [high_priority, low_priority, with_meta]:
            result = executor.get_result(task_id, timeout=5.0)
            print(f"   Task {task_id[:8]}...: {result.value}")

        # Check statistics
        stats = executor.get_stats()
        print(f"\n   Statistics:")
        print(f"   - Submitted: {stats.tasks_submitted}")
        print(f"   - Completed: {stats.tasks_completed}")
        print(f"   - Avg time: {stats.avg_execution_time:.4f}s")
        print(f"   - Success rate: {stats.success_rate:.0%}")

    print("\n" + "=" * 60)
    print("Examples completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
