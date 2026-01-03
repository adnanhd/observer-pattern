#!/usr/bin/env python3
"""
Distributed Task Queue - Application Example
Demonstrates task queue with workers and result aggregation.
"""

import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from callpyback import (
    ExecutionMode,
    Executor,
    MessageQueue,
    Meter,
    MetricsObserver,
    TimingObserver,
    observe,
)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    task_id: str
    task_type: str
    payload: Dict[str, Any]
    priority: int = 0
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class TaskResult:
    task_id: str
    status: TaskStatus
    result: Any = None
    error: Optional[str] = None
    worker_id: str = ""
    execution_time: float = 0.0


def main():
    queue = MessageQueue()
    timing = TimingObserver()
    metrics = MetricsObserver()
    exec_time_meter = Meter("exec_time")

    results: Dict[str, TaskResult] = {}
    pending_tasks: List[Task] = []

    # Task handlers
    @queue.on("task.submitted")
    def on_task_submitted(msg):
        task = msg.payload
        print(f"Task submitted: {task['task_id']} ({task['task_type']})")
        pending_tasks.append(
            Task(
                task_id=task["task_id"],
                task_type=task["task_type"],
                payload=task["payload"],
                priority=task.get("priority", 0),
            )
        )

    @queue.on("task.started")
    def on_task_started(msg):
        task = msg.payload
        print(f"  Worker {task['worker_id']}: Starting {task['task_id']}")

    @queue.on("task.completed")
    def on_task_completed(msg):
        result = msg.payload
        results[result["task_id"]] = TaskResult(
            task_id=result["task_id"],
            status=TaskStatus.COMPLETED,
            result=result["result"],
            worker_id=result["worker_id"],
            execution_time=result["execution_time"],
        )
        exec_time_meter.update(result["execution_time"])
        print(f"  Worker {result['worker_id']}: Completed {result['task_id']}")

    @queue.on("task.failed")
    def on_task_failed(msg):
        result = msg.payload
        results[result["task_id"]] = TaskResult(
            task_id=result["task_id"],
            status=TaskStatus.FAILED,
            error=result["error"],
            worker_id=result["worker_id"],
        )
        print(
            f"  Worker {result['worker_id']}: Failed {result['task_id']} - {result['error']}"
        )

    @queue.on("queue.stats")
    def on_queue_stats(msg):
        stats = msg.payload
        print(f"\n=== Queue Stats ===")
        print(f"  Completed: {stats['completed']}")
        print(f"  Failed: {stats['failed']}")
        print(f"  Avg exec time: {stats['avg_exec_time']:.3f}s")

    # Worker function
    @observe(timing, metrics)
    def process_task(task: Task, worker_id: str) -> dict:
        """Process a single task."""
        start = time.perf_counter()

        queue.publish(
            "task.started",
            {"task_id": task.task_id, "worker_id": worker_id},
        )

        try:
            # Simulate work based on task type
            if task.task_type == "compute":
                time.sleep(random.uniform(0.05, 0.15))
                result = sum(range(task.payload.get("n", 1000)))
            elif task.task_type == "io":
                time.sleep(random.uniform(0.1, 0.2))
                result = f"fetched_{task.payload.get('url', 'data')}"
            else:
                time.sleep(0.05)
                result = "processed"

            # Simulate occasional failures
            if random.random() < 0.1:
                raise RuntimeError("Random failure")

            exec_time = time.perf_counter() - start

            queue.publish(
                "task.completed",
                {
                    "task_id": task.task_id,
                    "result": result,
                    "worker_id": worker_id,
                    "execution_time": exec_time,
                },
            )

            return {"status": "completed", "result": result}

        except Exception as e:
            queue.publish(
                "task.failed",
                {
                    "task_id": task.task_id,
                    "error": str(e),
                    "worker_id": worker_id,
                },
            )
            return {"status": "failed", "error": str(e)}

    # Submit tasks
    print("=== Distributed Task Queue Demo ===\n")

    tasks = [
        {
            "task_id": f"task-{i}",
            "task_type": random.choice(["compute", "io"]),
            "payload": {"n": 1000 * i, "url": f"http://example.com/{i}"},
            "priority": random.randint(0, 2),
        }
        for i in range(10)
    ]

    for task in tasks:
        queue.publish("task.submitted", task)

    time.sleep(0.1)

    # Process tasks with worker pool
    print("\nProcessing tasks with 4 workers...\n")

    with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
        task_futures = []

        for i, task in enumerate(pending_tasks):
            worker_id = f"worker-{i % 4}"
            task_futures.append(executor.submit(process_task, task, worker_id))

        # Wait for completion
        for future_id in task_futures:
            executor.result(future_id)

    # Report stats
    completed = sum(1 for r in results.values() if r.status == TaskStatus.COMPLETED)
    failed = sum(1 for r in results.values() if r.status == TaskStatus.FAILED)

    queue.publish(
        "queue.stats",
        {
            "completed": completed,
            "failed": failed,
            "avg_exec_time": exec_time_meter.avg if exec_time_meter.count > 0 else 0,
        },
    )

    time.sleep(0.1)

    print(f"\nTiming: {timing.stats}")
    print(f"Metrics: {metrics.stats}")


if __name__ == "__main__":
    main()
