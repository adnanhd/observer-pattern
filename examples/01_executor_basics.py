"""Basic Executor usage - parallel task execution.

Demonstrates:
- ExecutionMode (SEQUENTIAL, THREAD, PROCESS)
- Submitting tasks and getting results
- Error handling
"""

import time

from callpyback import ExecutionMode, Executor


def cpu_work(n: int) -> int:
    """Simulate CPU-bound work."""
    total = 0
    for i in range(n * 100000):
        total += i % 17
    return total


def io_work(delay: float) -> str:
    """Simulate I/O-bound work."""
    time.sleep(delay)
    return f"slept {delay}s"


def failing_task() -> None:
    """Task that raises an exception."""
    raise ValueError("intentional error")


def main():
    # Sequential execution (default)
    print("=== Sequential Executor ===")
    executor = Executor(mode=ExecutionMode.SEQUENTIAL)

    task_id = executor.submit(cpu_work, 10)
    result = executor.result(task_id)
    print(f"Result: {result.value}")

    # Thread executor - good for I/O-bound tasks
    print("\n=== Thread Executor ===")
    executor = Executor(mode=ExecutionMode.THREAD, max_workers=4)

    # Submit multiple I/O tasks
    task_ids = [executor.submit(io_work, 0.1) for _ in range(4)]

    start = time.time()
    results = [executor.result(tid) for tid in task_ids]
    elapsed = time.time() - start

    print(f"4 x 0.1s tasks completed in {elapsed:.2f}s (parallel)")

    # Process executor - good for CPU-bound tasks
    print("\n=== Process Executor ===")
    executor = Executor(mode=ExecutionMode.PROCESS, max_workers=2)

    task_ids = [executor.submit(cpu_work, 20) for _ in range(2)]
    results = [executor.result(tid) for tid in task_ids]
    print(f"Results: {[r.value for r in results]}")

    # Error handling
    print("\n=== Error Handling ===")
    executor = Executor(mode=ExecutionMode.THREAD)

    task_id = executor.submit(failing_task)
    result = executor.result(task_id)

    if result.is_failure:
        print(f"Task failed: {result.error}")


if __name__ == "__main__":
    main()
