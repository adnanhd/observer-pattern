"""@task decorator - unified task execution with lifecycle hooks.

Demonstrates:
- @task decorator with queue integration
- Lifecycle callbacks (on_success, on_failure, on_complete)
- Observer integration with @task
- max_instances for concurrency limiting
"""

import threading
import time

from callpyback import (
    ExecutionMode,
    Executor,
    MessageQueue,
    MetricsObserver,
    TimingObserver,
    task,
)


def main():
    queue = MessageQueue()
    executor = Executor(mode=ExecutionMode.THREAD, max_workers=4)

    # Basic @task
    print("=== Basic @task ===")

    @task(executor=executor)
    def simple_task(x: int) -> int:
        return x * 2

    result = simple_task(21)
    print(f"Result: {result}")

    # @task with observers
    print("\n=== @task with Observers ===")

    timing = TimingObserver()
    metrics = MetricsObserver()

    @task(
        executor=executor,
        on_execute=[timing, metrics],
    )
    def observed_task(delay: float) -> str:
        time.sleep(delay)
        return f"slept {delay}s"

    observed_task(0.05)
    observed_task(0.1)

    print(f"Timing: {timing.stats}")
    print(f"Metrics: {metrics.stats}")

    # @task with lifecycle callbacks
    print("\n=== Lifecycle Callbacks ===")

    results = []

    @task(
        executor=executor,
        on_success=lambda ctx: results.append(f"success: {ctx.result}"),
        on_failure=lambda ctx: results.append(f"failure: {ctx.error}"),
        on_complete=lambda ctx: results.append(f"complete: {ctx.func_name}"),
    )
    def lifecycle_task(should_fail: bool):
        if should_fail:
            raise ValueError("intentional")
        return "ok"

    lifecycle_task(False)
    try:
        lifecycle_task(True)
    except Exception:
        pass  # Exception is still raised after callbacks

    print(f"Lifecycle events: {results}")

    # @task with queue integration
    print("\n=== Queue Integration ===")

    processed = []

    @task(
        queue=queue,
        topic="jobs.process",
        executor=executor,
        on_success=lambda ctx: processed.append(ctx.result),
    )
    def process_job(data: str) -> str:
        return data.upper()

    # Direct call
    result = process_job("hello")
    print(f"Direct call: {result}")

    # Queue trigger
    queue.publish("jobs.process", "world")
    time.sleep(0.1)  # Let queue process

    print(f"Processed: {processed}")

    # @task with max_instances (load balancing)
    print("\n=== max_instances (Load Balancing) ===")

    active_count = []
    lock = threading.Lock()

    @task(
        executor=executor,
        max_instances=2,  # Only 2 concurrent executions
        on_execute=[TimingObserver()],
    )
    def limited_task(task_id: int) -> int:
        with lock:
            current = limited_task.pool.active
            active_count.append(current)
        time.sleep(0.1)
        return task_id

    # Submit 4 tasks, but only 2 can run at a time
    threads = []
    for i in range(4):
        t = threading.Thread(target=limited_task, args=(i,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    print(f"Max concurrent: {max(active_count)} (limit: 2)")
    print(f"Pool stats: {limited_task.pool.stats}")


if __name__ == "__main__":
    main()
