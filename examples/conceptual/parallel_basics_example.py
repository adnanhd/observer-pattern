#!/usr/bin/env python3
"""
Parallel Execution Basics - Conceptual Example
Demonstrates the fundamental concepts of the unified execution API.
"""

import random
import time


from functools import partial
from callpyback import ExecutionMode, execution_session, run_parallel


def cpu_task(n: int) -> int:
    """Simulate CPU-intensive work"""
    # Calculate sum of squares
    result = sum(i * i for i in range(n))
    return result


def io_task(delay: float) -> str:
    """Simulate I/O-bound work"""
    time.sleep(delay)
    return f"IO completed after {delay:.2f}s"


def mixed_task(task_id: str) -> dict:
    """Task that combines CPU and I/O work"""
    # Some CPU work
    cpu_result = sum(range(random.randint(100, 500)))

    # Some I/O work
    io_delay = random.uniform(0.1, 0.3)
    time.sleep(io_delay)

    return {
        "task_id": task_id,
        "cpu_result": cpu_result,
        "io_delay": io_delay,
        "thread": "simulated",
    }


def main():
    """Demonstrate basic parallel execution patterns"""
    print("⚡ Parallel Execution Basics")
    print("=" * 40)

    # Example 1: Global run_parallel function (simplest usage)
    print("\n1️⃣ Global Parallel Execution:")
    print("Running CPU and I/O tasks together...")

    start_time = time.time()
    results = run_parallel(
        lambda: cpu_task(1000),
        lambda: io_task(0.5),
        lambda: cpu_task(2000),
        lambda: io_task(0.3),
    )
    elapsed = time.time() - start_time

    print(f"   Results: {results}")
    print(f"   Completed in {elapsed:.2f}s (would take ~0.8s sequentially)")

    # Example 2: Context manager with configuration
    print("\n2️⃣ Configured Execution:")

    with execution_session() as manager:
        # Configure thread pool
        manager.configure().max_threads(3).execution_mode(ExecutionMode.THREAD).apply()

        # Run multiple similar tasks
        print("Processing batch of mixed tasks...")
        task_ids = [f"task_{i:02d}" for i in range(6)]

        start_time = time.time()
        batch_results = manager.map_parallel(mixed_task, task_ids)
        elapsed = time.time() - start_time

        print(f"   Processed {len(batch_results)} tasks in {elapsed:.2f}s")

        # Show some results
        for result in batch_results[:3]:
            print(
                f"   - {result['task_id']}: CPU={result['cpu_result']}, IO={result['io_delay']:.2f}s"
            )

        if len(batch_results) > 3:
            print(f"   ... and {len(batch_results) - 3} more")

    # Example 3: Different execution modes
    print("\n3️⃣ Execution Mode Comparison:")

    # Test different modes

    for mode in [ExecutionMode.THREAD, ExecutionMode.PROCESS, ExecutionMode.HYBRID]:
        with execution_session() as manager:
            (
                manager.configure()
                .auto_start(True)
                .max_threads(2)
                .max_processes(2)
                .enable_hybrid(ExecutionMode.HYBRID == mode)
                .execution_mode(mode)
                .apply()
            )
            print("manager mode", manager.config.default_execution_mode.name, "executor", manager.get_executor_mode())

            start_time = time.time()
            mode_results = manager.parallel(
                partial(cpu_task, 500),
                partial(io_task, 0.1),
                partial(cpu_task, 300),
                partial(io_task, 0.2),
            )
            elapsed = time.time() - start_time

            print(
                f"   {mode.value}: {len(mode_results)} tasks in {elapsed:.3f}s -- {manager.get_executor_mode()}"
            )

    # Example 4: Manager metrics
    print("\n4️⃣ Performance Metrics:")

    with execution_session() as manager:
        manager.configure().max_threads(4).apply()

        # Run some tasks to generate metrics
        manager.parallel(
            lambda: cpu_task(500), lambda: io_task(0.1), lambda: cpu_task(300)
        )

        # Show metrics
        metrics = manager.get_metrics()
        health = manager.health_check()

        print(f"   Tasks completed: {metrics['tasks_completed']}")
        print(f"   System health: {health}")

        if "thread_executor" in metrics:
            thread_stats = metrics["thread_executor"]
            print(f"   Thread pool: {thread_stats.get('active_threads', 'N/A')} active")

    print("\n✅ Parallel execution basics completed!")


if __name__ == "__main__":
    main()
