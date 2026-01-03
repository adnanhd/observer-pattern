#!/usr/bin/env python3
"""
Basic Executor Usage Examples

This example demonstrates the fundamental usage patterns for the Executor
in CallPyBack. The Executor supports different execution modes: SEQUENTIAL,
THREAD, and PROCESS.
"""

import time

from callpyback import ExecutionMode, Executor, TaskStatus


def simple_computation(x: int, y: int) -> int:
    """A simple computation function."""
    return x + y


def slow_io_operation(url: str) -> str:
    """Simulate an I/O operation."""
    time.sleep(0.1)  # Simulate network delay
    return f"Fetched: {url}"


def cpu_intensive_task(n: int) -> int:
    """CPU-intensive computation."""
    return sum(i**2 for i in range(n))


def main():
    print("=" * 60)
    print("CallPyBack Executors - Basic Usage Examples")
    print("=" * 60)

    # Example 1: Sequential Executor
    print("\n1. Sequential Executor")
    print("-" * 40)

    with Executor(mode=ExecutionMode.SEQUENTIAL) as executor:
        # Submit task
        task_id = executor.submit(simple_computation, 10, 20)
        print(f"   Submitted task: {task_id[:8]}...")

        # Get result
        result = executor.result(task_id)
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

    with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
        start_time = time.time()

        # Submit multiple I/O tasks
        task_ids = [executor.submit(slow_io_operation, url) for url in urls]
        print(f"   Submitted {len(task_ids)} tasks")

        # Collect results
        results = []
        for task_id in task_ids:
            result = executor.result(task_id, timeout=5.0)
            results.append(result.value)

        elapsed = time.time() - start_time
        print(f"   All tasks completed in {elapsed:.3f}s")
        print(f"   (Sequential would take ~{len(urls) * 0.1:.1f}s)")

    # Example 3: Process Executor
    print("\n3. Process Executor (Parallel CPU)")
    print("-" * 40)

    # Note: For PROCESS mode, functions must be defined at module level
    # (they need to be picklable)

    with Executor(mode=ExecutionMode.PROCESS, max_workers=4) as executor:
        start_time = time.time()

        # Submit CPU-intensive tasks
        task_ids = [executor.submit(cpu_intensive_task, 100000) for _ in range(4)]
        print(f"   Submitted {len(task_ids)} CPU tasks")

        # Collect results
        for i, task_id in enumerate(task_ids):
            result = executor.result(task_id, timeout=30.0)
            print(f"   Task {i + 1}: {result.value:,}")

        elapsed = time.time() - start_time
        print(f"   Completed in {elapsed:.3f}s")

    # Example 4: Mixed Workload
    print("\n4. Mixed Workload (Thread + Process)")
    print("-" * 40)

    # Use thread executor for I/O-bound tasks
    with Executor(mode=ExecutionMode.THREAD, max_workers=4) as thread_executor:
        io_task = thread_executor.submit(slow_io_operation, "https://example.com")
        io_result = thread_executor.result(io_task, timeout=5.0)
        print(f"   I/O result: {io_result.value[:30]}...")

    # Use process executor for CPU-bound tasks
    with Executor(mode=ExecutionMode.PROCESS, max_workers=2) as process_executor:
        cpu_task = process_executor.submit(cpu_intensive_task, 50000)
        cpu_result = process_executor.result(cpu_task, timeout=30.0)
        print(f"   CPU result: {cpu_result.value:,}")

    # Example 5: Batch Submission
    print("\n5. Batch Submission")
    print("-" * 40)

    with Executor(mode=ExecutionMode.THREAD, max_workers=2) as executor:
        # Submit multiple tasks
        task_ids = [
            executor.submit(simple_computation, 1, 2),
            executor.submit(simple_computation, 3, 4),
            executor.submit(simple_computation, 5, 6),
        ]

        # Get results
        results = []
        for task_id in task_ids:
            result = executor.result(task_id, timeout=5.0)
            results.append(result.value)
            print(f"   Task {task_id[:8]}...: {result.value}")

        print(f"\n   All results: {results}")

    # Example 6: Map Operation
    print("\n6. Map Operation")
    print("-" * 40)

    def square(x):
        return x * x

    with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
        items = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        results = executor.map(square, items)

        print(f"   Input: {items}")
        print(f"   Output: {[r.value for r in results]}")

    print("\n" + "=" * 60)
    print("Examples completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
