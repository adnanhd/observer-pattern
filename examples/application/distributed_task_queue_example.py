#!/usr/bin/env python3
"""
Distributed Task Queue - Application Example
Demonstrates job scheduling, worker management, and task distribution.
"""

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from callpyback import ExecutionMode, emit_event, on_event, plugin_session


class TaskStatus(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class TaskPriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Task:
    id: str
    task_type: str
    payload: Dict[str, Any]
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    worker_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    timeout: float = 300.0  # 5 minutes default
    result: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerInfo:
    worker_id: str
    worker_type: str
    capacity: int
    current_load: int = 0
    status: str = "idle"  # idle, busy, offline
    last_heartbeat: float = field(default_factory=time.time)
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_processing_time: float = 0.0


# Task queue event handlers
@on_event("task.*.submitted")
def handle_task_submitted(message):
    """Handle task submission events"""
    task_type = message.topic.split(".")[1]
    task_id = message.payload.get("task_id", "unknown")
    priority = message.payload.get("priority", "normal")
    print(f"📝 Task submitted: {task_type} ({task_id}) - Priority: {priority}")


@on_event("task.*.started")
def handle_task_started(message):
    """Handle task start events"""
    task_type = message.topic.split(".")[1]
    payload = message.payload
    task_id = payload.get("task_id", "unknown")
    worker_id = payload.get("worker_id", "unknown")
    queue_time = payload.get("queue_time", 0)
    print(
        f"🚀 Task started: {task_type} ({task_id}) by {worker_id} (queued: {queue_time:.2f}s)"
    )


@on_event("task.*.completed")
def handle_task_completed(message):
    """Handle task completion events"""
    task_type = message.topic.split(".")[1]
    payload = message.payload
    task_id = payload.get("task_id", "unknown")
    worker_id = payload.get("worker_id", "unknown")
    processing_time = payload.get("processing_time", 0)
    print(
        f"✅ Task completed: {task_type} ({task_id}) by {worker_id} in {processing_time:.2f}s"
    )


@on_event("task.*.failed")
def handle_task_failed(message):
    """Handle task failure events"""
    task_type = message.topic.split(".")[1]
    payload = message.payload
    task_id = payload.get("task_id", "unknown")
    worker_id = payload.get("worker_id", "unknown")
    error = payload.get("error", "Unknown error")
    retry_count = payload.get("retry_count", 0)
    print(
        f"❌ Task failed: {task_type} ({task_id}) by {worker_id} - {error} (retry {retry_count})"
    )


@on_event("worker.*.status")
def handle_worker_status(message):
    """Handle worker status updates"""
    worker_type = message.topic.split(".")[1]
    payload = message.payload
    worker_id = payload.get("worker_id", "unknown")
    status = payload.get("status", "unknown")
    load = payload.get("current_load", 0)
    capacity = payload.get("capacity", 1)
    print(f"👷 Worker {worker_id} ({worker_type}): {status} (load: {load}/{capacity})")


@on_event("queue.*.stats")
def handle_queue_stats(message):
    """Handle queue statistics"""
    queue_type = message.topic.split(".")[1]
    payload = message.payload
    pending = payload.get("pending_tasks", 0)
    processing = payload.get("processing_tasks", 0)
    throughput = payload.get("throughput", 0)
    print(
        f"📊 Queue {queue_type}: {pending} pending, {processing} processing "
        f"(throughput: {throughput:.1f} tasks/min)"
    )


class TaskQueue:
    """Distributed task queue with priority and worker management"""

    def __init__(self, queue_name: str):
        self.queue_name = queue_name
        self.tasks: Dict[str, Task] = {}
        self.workers: Dict[str, WorkerInfo] = {}
        self.task_queues: Dict[TaskPriority, List[str]] = {
            priority: [] for priority in TaskPriority
        }
        self.processing_tasks: Dict[str, str] = {}  # task_id -> worker_id
        self.completed_tasks: List[str] = []
        self.failed_tasks: List[str] = []

        # Statistics
        self.stats = {
            "tasks_submitted": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "total_processing_time": 0.0,
        }

    def submit_task(self, task: Task) -> str:
        """Submit a task to the queue"""
        task.status = TaskStatus.QUEUED
        self.tasks[task.id] = task
        self.task_queues[task.priority].append(task.id)
        self.stats["tasks_submitted"] += 1

        emit_event(
            f"task.{task.task_type}.submitted",
            {
                "task_id": task.id,
                "task_type": task.task_type,
                "priority": task.priority.name,
                "queue_name": self.queue_name,
            },
        )

        return task.id

    def register_worker(self, worker: WorkerInfo):
        """Register a worker with the queue"""
        self.workers[worker.worker_id] = worker

        emit_event(
            f"worker.{worker.worker_type}.registered",
            {
                "worker_id": worker.worker_id,
                "worker_type": worker.worker_type,
                "capacity": worker.capacity,
                "queue_name": self.queue_name,
            },
        )

    def get_next_task(self, worker_id: str) -> Optional[Task]:
        """Get the next highest priority task for a worker"""
        worker = self.workers.get(worker_id)
        if not worker or worker.current_load >= worker.capacity:
            return None

        # Find highest priority task
        for priority in reversed(list(TaskPriority)):
            if self.task_queues[priority]:
                task_id = self.task_queues[priority].pop(0)
                task = self.tasks[task_id]

                # Assign task to worker
                task.status = TaskStatus.PROCESSING
                task.worker_id = worker_id
                task.started_at = time.time()
                worker.current_load += 1
                worker.status = (
                    "busy" if worker.current_load >= worker.capacity else "idle"
                )

                self.processing_tasks[task_id] = worker_id

                queue_time = task.started_at - task.created_at

                emit_event(
                    f"task.{task.task_type}.started",
                    {
                        "task_id": task.id,
                        "task_type": task.task_type,
                        "worker_id": worker_id,
                        "queue_time": queue_time,
                        "priority": task.priority.name,
                    },
                )

                return task

        return None

    def complete_task(self, task_id: str, result: Any = None):
        """Mark a task as completed"""
        task = self.tasks.get(task_id)
        if not task:
            return

        task.status = TaskStatus.COMPLETED
        task.completed_at = time.time()
        task.result = result

        # Update worker status
        worker = self.workers.get(task.worker_id)
        if worker:
            worker.current_load = max(0, worker.current_load - 1)
            worker.status = "idle" if worker.current_load == 0 else "busy"
            worker.tasks_completed += 1

            processing_time = task.completed_at - task.started_at
            worker.total_processing_time += processing_time

        # Update queue tracking
        self.processing_tasks.pop(task_id, None)
        self.completed_tasks.append(task_id)
        self.stats["tasks_completed"] += 1
        self.stats["total_processing_time"] += processing_time

        emit_event(
            f"task.{task.task_type}.completed",
            {
                "task_id": task.id,
                "task_type": task.task_type,
                "worker_id": task.worker_id,
                "processing_time": processing_time,
                "result_size": len(str(result)) if result else 0,
            },
        )

    def fail_task(self, task_id: str, error: str):
        """Mark a task as failed and handle retries"""
        task = self.tasks.get(task_id)
        if not task:
            return

        task.retry_count += 1
        task.error = error

        # Update worker status
        worker = self.workers.get(task.worker_id)
        if worker:
            worker.current_load = max(0, worker.current_load - 1)
            worker.status = "idle" if worker.current_load == 0 else "busy"
            worker.tasks_failed += 1

        self.processing_tasks.pop(task_id, None)

        if task.retry_count <= task.max_retries:
            # Retry the task
            task.status = TaskStatus.RETRYING
            task.worker_id = None
            task.started_at = None

            # Re-queue with slightly lower priority to prevent blocking
            retry_priority = (
                TaskPriority.LOW
                if task.priority == TaskPriority.NORMAL
                else task.priority
            )
            self.task_queues[retry_priority].append(task_id)

            emit_event(
                f"task.{task.task_type}.retrying",
                {
                    "task_id": task.id,
                    "task_type": task.task_type,
                    "retry_count": task.retry_count,
                    "max_retries": task.max_retries,
                    "error": error,
                },
            )
        else:
            # Task has exceeded max retries
            task.status = TaskStatus.FAILED
            task.completed_at = time.time()
            self.failed_tasks.append(task_id)
            self.stats["tasks_failed"] += 1

            emit_event(
                f"task.{task.task_type}.failed",
                {
                    "task_id": task.id,
                    "task_type": task.task_type,
                    "worker_id": task.worker_id,
                    "error": error,
                    "retry_count": task.retry_count,
                    "final_failure": True,
                },
            )

    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        pending_tasks = sum(len(queue) for queue in self.task_queues.values())
        processing_tasks = len(self.processing_tasks)

        # Calculate throughput (tasks per minute)
        if (
            self.stats["tasks_completed"] > 0
            and self.stats["total_processing_time"] > 0
        ):
            avg_processing_time = (
                self.stats["total_processing_time"] / self.stats["tasks_completed"]
            )
            throughput = 60.0 / avg_processing_time if avg_processing_time > 0 else 0
        else:
            throughput = 0

        stats = {
            "queue_name": self.queue_name,
            "pending_tasks": pending_tasks,
            "processing_tasks": processing_tasks,
            "completed_tasks": len(self.completed_tasks),
            "failed_tasks": len(self.failed_tasks),
            "total_workers": len(self.workers),
            "active_workers": sum(
                1 for w in self.workers.values() if w.status != "offline"
            ),
            "throughput": throughput,
            **self.stats,
        }

        emit_event(f"queue.{self.queue_name}.stats", stats)
        return stats


class TaskWorker:
    """Generic task worker that processes tasks from the queue"""

    def __init__(self, worker_id: str, worker_type: str, capacity: int = 1):
        self.worker_info = WorkerInfo(worker_id, worker_type, capacity)
        self.task_processors: Dict[str, Callable] = {}
        self.running = False

    def register_task_processor(self, task_type: str, processor: Callable):
        """Register a processor function for a specific task type"""
        self.task_processors[task_type] = processor

    def process_tasks(self, task_queue: TaskQueue, max_tasks: int = 10):
        """Process tasks from the queue"""
        task_queue.register_worker(self.worker_info)
        self.running = True
        tasks_processed = 0

        try:
            while self.running and tasks_processed < max_tasks:
                # Get next task
                task = task_queue.get_next_task(self.worker_info.worker_id)

                if task is None:
                    time.sleep(0.1)  # Wait briefly before checking again
                    continue

                # Process the task
                try:
                    processor = self.task_processors.get(task.task_type)
                    if processor:
                        result = processor(task)
                        task_queue.complete_task(task.id, result)
                    else:
                        raise ValueError(
                            f"No processor for task type: {task.task_type}"
                        )

                    tasks_processed += 1

                except Exception as e:
                    task_queue.fail_task(task.id, str(e))

                # Update worker heartbeat
                self.worker_info.last_heartbeat = time.time()

                # Emit worker status
                emit_event(
                    f"worker.{self.worker_info.worker_type}.status",
                    {
                        "worker_id": self.worker_info.worker_id,
                        "status": self.worker_info.status,
                        "current_load": self.worker_info.current_load,
                        "capacity": self.worker_info.capacity,
                        "tasks_completed": self.worker_info.tasks_completed,
                        "tasks_failed": self.worker_info.tasks_failed,
                    },
                )

        finally:
            self.running = False
            self.worker_info.status = "offline"


# Task processor functions
def process_image_task(task: Task) -> Dict[str, Any]:
    """Process image manipulation tasks"""
    # Simulate image processing work
    image_size = task.payload.get("image_size", "medium")
    operations = task.payload.get("operations", ["resize"])

    processing_time_map = {"small": 0.1, "medium": 0.3, "large": 0.8}
    base_time = processing_time_map.get(image_size, 0.3)

    # Add time for each operation
    total_time = base_time * len(operations)
    time.sleep(total_time)

    # Simulate occasional failures
    if random.random() < 0.05:  # 5% failure rate
        raise Exception("Image processing failed: corrupted file")

    return {
        "processed_image_url": f"/processed/{task.id}.jpg",
        "operations_applied": operations,
        "processing_time": total_time,
        "output_size": f"{random.randint(100, 1000)}KB",
    }


def process_email_task(task: Task) -> Dict[str, Any]:
    """Process email sending tasks"""
    # Simulate email sending
    recipients = task.payload.get("recipients", [])
    template = task.payload.get("template", "default")

    # Processing time scales with number of recipients
    processing_time = 0.05 + len(recipients) * 0.02
    time.sleep(processing_time)

    # Simulate occasional delivery failures
    if random.random() < 0.03:  # 3% failure rate
        raise Exception("Email delivery failed: SMTP timeout")

    return {
        "emails_sent": len(recipients),
        "template_used": template,
        "delivery_time": processing_time,
        "message_id": f"msg_{task.id}_{int(time.time())}",
    }


def process_data_analysis_task(task: Task) -> Dict[str, Any]:
    """Process data analysis tasks"""
    # Simulate data analysis work
    dataset_size = task.payload.get("dataset_size", 1000)
    analysis_type = task.payload.get("analysis_type", "basic")

    # Analysis time scales with dataset size
    time_factor = {"basic": 0.001, "advanced": 0.005, "ml": 0.01}
    processing_time = dataset_size * time_factor.get(analysis_type, 0.001)

    # Add some randomness
    processing_time *= random.uniform(0.8, 1.2)
    time.sleep(min(processing_time, 2.0))  # Cap at 2 seconds for demo

    # Simulate analysis failure for very large datasets
    if dataset_size > 5000 and random.random() < 0.1:
        raise Exception("Analysis failed: dataset too large")

    # Generate analysis results
    return {
        "analysis_type": analysis_type,
        "dataset_size": dataset_size,
        "processing_time": processing_time,
        "insights_found": random.randint(3, 12),
        "confidence_score": random.uniform(0.7, 0.95),
        "output_file": f"/analysis/{task.id}_results.json",
    }


def create_sample_tasks(count: int) -> List[Task]:
    """Create sample tasks for testing"""
    tasks = []
    task_types = ["image_processing", "email_sending", "data_analysis"]
    priorities = list(TaskPriority)

    for i in range(count):
        task_type = random.choice(task_types)
        priority = random.choice(priorities)

        if task_type == "image_processing":
            payload = {
                "image_url": f"/uploads/image_{i}.jpg",
                "image_size": random.choice(["small", "medium", "large"]),
                "operations": random.sample(
                    ["resize", "crop", "filter", "compress"], random.randint(1, 3)
                ),
            }
        elif task_type == "email_sending":
            payload = {
                "recipients": [
                    f"user{j}@example.com" for j in range(random.randint(1, 5))
                ],
                "template": random.choice(["welcome", "newsletter", "reminder"]),
                "subject": f"Task {i} Email",
                "priority": (
                    "high"
                    if priority in [TaskPriority.HIGH, TaskPriority.CRITICAL]
                    else "normal"
                ),
            }
        else:  # data_analysis
            payload = {
                "dataset_size": random.randint(100, 5000),
                "analysis_type": random.choice(["basic", "advanced", "ml"]),
                "output_format": random.choice(["json", "csv", "pdf"]),
            }

        task = Task(
            id=f"task_{int(time.time() * 1000) % 100000}_{i:03d}",
            task_type=task_type,
            payload=payload,
            priority=priority,
            max_retries=random.randint(1, 3),
        )
        tasks.append(task)

    return tasks


def main():
    """Demo distributed task queue system"""
    print("📋 Distributed Task Queue System")
    print("=" * 50)

    # Create task queue
    task_queue = TaskQueue("main_queue")

    # Create workers with different capabilities
    image_worker = TaskWorker("img_worker_001", "image_processor", capacity=2)
    image_worker.register_task_processor("image_processing", process_image_task)

    email_worker = TaskWorker("email_worker_001", "email_sender", capacity=3)
    email_worker.register_task_processor("email_sending", process_email_task)

    analytics_worker = TaskWorker("analytics_worker_001", "data_analyst", capacity=1)
    analytics_worker.register_task_processor(
        "data_analysis", process_data_analysis_task
    )

    # Multi-purpose worker
    general_worker = TaskWorker("general_worker_001", "general_purpose", capacity=2)
    general_worker.register_task_processor("image_processing", process_image_task)
    general_worker.register_task_processor("email_sending", process_email_task)
    general_worker.register_task_processor("data_analysis", process_data_analysis_task)

    workers = [image_worker, email_worker, analytics_worker, general_worker]

    with plugin_session() as manager:
        # Configure for I/O intensive task processing
        manager.configure().max_threads(6).execution_mode(ExecutionMode.THREAD).apply()

        print("📝 Submitting tasks to queue...")

        # Create and submit tasks
        tasks = create_sample_tasks(30)

        for task in tasks:
            task_queue.submit_task(task)

        print(f"   Submitted {len(tasks)} tasks to queue")

        # Start workers in parallel
        print(f"\n👷 Starting {len(workers)} workers...")

        start_time = time.time()
        worker_results = manager.parallel(
            *[
                lambda w=worker: w.process_tasks(task_queue, max_tasks=15)
                for worker in workers
            ]
        )
        processing_time = time.time() - start_time

        print(f"\n📊 Task Processing Summary:")

        # Get final queue statistics
        final_stats = task_queue.get_queue_stats()

        print(f"   Tasks submitted: {final_stats['tasks_submitted']}")
        print(f"   Tasks completed: {final_stats['completed_tasks']}")
        print(f"   Tasks failed: {final_stats['failed_tasks']}")
        print(f"   Tasks pending: {final_stats['pending_tasks']}")
        print(f"   Processing time: {processing_time:.2f}s")
        print(f"   Throughput: {final_stats['throughput']:.1f} tasks/min")

        # Show worker statistics
        print(f"\n👷 Worker Performance:")
        for worker in workers:
            info = worker.worker_info
            avg_time = (
                info.total_processing_time / info.tasks_completed
                if info.tasks_completed > 0
                else 0
            )
            success_rate = (
                info.tasks_completed / (info.tasks_completed + info.tasks_failed) * 100
                if (info.tasks_completed + info.tasks_failed) > 0
                else 0
            )

            print(f"   {info.worker_id}:")
            print(f"     Tasks completed: {info.tasks_completed}")
            print(f"     Tasks failed: {info.tasks_failed}")
            print(f"     Success rate: {success_rate:.1f}%")
            print(f"     Avg processing time: {avg_time:.3f}s")

        # Show task type breakdown
        task_type_stats = {}
        for task in tasks:
            task_type = task.task_type
            if task_type not in task_type_stats:
                task_type_stats[task_type] = {"completed": 0, "failed": 0, "pending": 0}

            if task.status == TaskStatus.COMPLETED:
                task_type_stats[task_type]["completed"] += 1
            elif task.status == TaskStatus.FAILED:
                task_type_stats[task_type]["failed"] += 1
            else:
                task_type_stats[task_type]["pending"] += 1

        print(f"\n📋 Task Type Breakdown:")
        for task_type, stats in task_type_stats.items():
            total = sum(stats.values())
            print(
                f"   {task_type}: {stats['completed']} completed, "
                f"{stats['failed']} failed, {stats['pending']} pending ({total} total)"
            )

        # Show system performance
        metrics = manager.get_metrics()
        print(f"\n🖥️ System Performance:")
        print(f"   Worker threads: {metrics['tasks_completed']}")
        print(f"   Queue events: {metrics['events_published']}")
        print(f"   System health: {manager.health_check()}")

        print(f"\n🎯 Task Queue demonstrates:")
        print(f"   ✅ Priority-based task scheduling")
        print(f"   ✅ Multi-worker task processing")
        print(f"   ✅ Automatic retry mechanisms")
        print(f"   ✅ Worker load balancing")
        print(f"   ✅ Real-time monitoring and stats")


if __name__ == "__main__":
    main()
