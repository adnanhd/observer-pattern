"""Full example - combining all features.

A job processing system with:
- Queue-based job submission
- Parallel execution with thread pool
- Observer-based monitoring
- Load balancing with max_instances
- Success/failure tracking
"""

import random
import threading
import time

from eventforge import (
    ExecutionMode,
    Executor,
    MessageQueue,
    MetricsMeter,
    TimingMeter,
    task,
)


def main():
    print("=== Job Processing System ===\n")

    # Setup
    queue = MessageQueue()
    executor = Executor(mode=ExecutionMode.THREAD, max_workers=8)

    timing = TimingMeter()
    metrics = MetricsMeter()

    # Track results
    results = {"success": [], "failure": []}
    lock = threading.Lock()

    def on_success(ctx):
        with lock:
            results["success"].append(
                {
                    "job_id": ctx.kwargs.get("job_id"),
                    "result": ctx.result,
                    "time": ctx.execution_time,
                }
            )

    def on_failure(ctx):
        with lock:
            results["failure"].append(
                {
                    "job_id": ctx.kwargs.get("job_id"),
                    "error": str(ctx.error),
                }
            )

    # Define the worker task
    @task(
        queue=queue,
        topic="jobs.work",
        executor=executor,
        max_instances=3,  # Max 3 concurrent workers
        on_execute=[timing, metrics],
        on_success=on_success,
        on_failure=on_failure,
    )
    def process_job(job_id: int, data: str) -> dict:
        """Process a job - may fail randomly."""
        # Simulate work
        work_time = random.uniform(0.05, 0.2)
        time.sleep(work_time)

        # Random failure (20% chance)
        if random.random() < 0.2:
            raise ValueError(f"Job {job_id} failed randomly")

        return {
            "job_id": job_id,
            "processed": data.upper(),
            "work_time": round(work_time, 3),
        }

    # Subscribe to results
    @queue.on("jobs.work.success")
    def on_job_success(msg):
        print(f"  [OK] Job {msg.payload['task_id'][:8]}... completed")

    @queue.on("jobs.work.failure")
    def on_job_failure(msg):
        print(
            f"  [FAIL] Job {msg.payload['task_id'][:8]}... error: {msg.payload['error']}"
        )

    # Submit jobs - wrap in try/except since failures raise
    print("Submitting 10 jobs...\n")

    def run_job(job_id):
        try:
            process_job(job_id=job_id, data=f"data-{job_id}")
        except Exception:
            pass  # Failure already tracked via on_failure callback

    threads = []
    for i in range(10):
        t = threading.Thread(target=run_job, args=(i,))
        t.start()
        threads.append(t)

    # Wait for completion
    for t in threads:
        t.join()

    # Allow queue events to process
    time.sleep(0.1)

    # Print summary
    print(f"\n=== Summary ===")
    print(f"Successful: {len(results['success'])}")
    print(f"Failed: {len(results['failure'])}")
    print(f"\nTiming stats: {timing.stats}")
    print(f"Metrics: {metrics.stats}")
    print(f"Pool stats: {process_job.pool.stats}")


if __name__ == "__main__":
    main()
