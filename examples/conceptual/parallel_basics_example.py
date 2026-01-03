#!/usr/bin/env python3
"""
Parallel Basics - Conceptual Example
Demonstrates parallel execution with different modes.
"""

import time

from callpyback import ExecutionMode, Executor, MetricsObserver, TimingObserver, observe


def cpu_task(n: int) -> int:
    """Simulate CPU-intensive work."""
    return sum(i * i for i in range(n))


def io_task(duration: float) -> str:
    """Simulate I/O-bound work."""
    time.sleep(duration)
    return f"slept {duration}s"


def main():
    timing = TimingObserver()
    metrics = MetricsObserver()

    print("=== Sequential Execution ===")
    with Executor(mode=ExecutionMode.SEQUENTIAL) as executor:
        start = time.perf_counter()

        task_ids = [executor.submit(cpu_task, 10000) for _ in range(4)]
        results = [executor.result(tid) for tid in task_ids]

        elapsed = time.perf_counter() - start
        print(f"4 tasks completed in {elapsed:.3f}s (sequential)")
        print(f"Results: {[r.value for r in results]}")

    print("\n=== Thread Execution (I/O-bound) ===")
    with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
        start = time.perf_counter()

        # Submit 4 I/O tasks that each take 0.1s
        task_ids = [executor.submit(io_task, 0.1) for _ in range(4)]
        results = [executor.result(tid) for tid in task_ids]

        elapsed = time.perf_counter() - start
        print(f"4 I/O tasks completed in {elapsed:.3f}s (parallel threads)")
        print(f"Expected ~0.1s with parallelism, 0.4s without")

    print("\n=== Process Execution (CPU-bound) ===")
    with Executor(mode=ExecutionMode.PROCESS, max_workers=4) as executor:
        start = time.perf_counter()

        # Use map for parallel execution
        results = executor.map(cpu_task, [100000, 100000, 100000, 100000])

        elapsed = time.perf_counter() - start
        print(f"4 CPU tasks completed in {elapsed:.3f}s (parallel processes)")
        print(f"All succeeded: {all(r.is_success for r in results)}")

    print("\n=== Mixed Workload with Observers ===")

    @observe(timing, metrics)
    def monitored_task(n: int) -> int:
        return cpu_task(n)

    for i in range(5):
        monitored_task(10000 + i * 1000)

    print(f"Timing: avg={timing.stats['avg'] * 1000:.2f}ms")
    print(
        f"Metrics: {metrics.stats['calls']} calls, {metrics.stats['successes']} success"
    )

    print("\n=== Error Handling ===")

    def failing_task(should_fail: bool):
        if should_fail:
            raise ValueError("Task failed!")
        return "success"

    with Executor(mode=ExecutionMode.THREAD) as executor:
        task1 = executor.submit(failing_task, False)
        task2 = executor.submit(failing_task, True)
        task3 = executor.submit(failing_task, False)

        for tid in [task1, task2, task3]:
            result = executor.result(tid)
            if result.is_success:
                print(f"Task {tid[:8]}: {result.value}")
            else:
                print(f"Task {tid[:8]}: FAILED - {result.error}")

    print("\nDone!")


if __name__ == "__main__":
    main()
