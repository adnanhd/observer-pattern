"""
Thread-based executor for parallel task execution.
Provides thread pool management with CallPyBack integration.
"""

import logging
import queue
import threading
import time
from concurrent.futures import ALL_COMPLETED, Future, ThreadPoolExecutor, as_completed
from concurrent.futures import wait as wait_for_futures
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from callpyback import CallPyBack


@dataclass
class Task:
    """Task container for execution."""

    id: str = field(default_factory=lambda: str(uuid4()))
    callable: Callable = field(default=lambda: None)
    args: tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    timeout: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def __lt__(self, other):
        """Priority queue ordering (higher priority first)."""
        return self.priority > other.priority


@dataclass
class TaskResult:
    """Task execution result."""

    task_id: str
    success: bool
    result: Any = None
    error: Optional[Exception] = None
    execution_time: float = 0.0
    worker_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class ThreadExecutor:
    """
    Advanced thread-based executor with priority queues and load balancing.

    Features:
    - Priority-based task scheduling
    - Thread pool management
    - Task timeout and retry logic
    - Load balancing across threads
    - Task cancellation support
    - Comprehensive monitoring
    """

    def __init__(
        self,
        max_workers: int = 4,
        queue_size: int = 1000,
        enable_priority: bool = True,
        default_timeout: float = 60.0,
    ):
        """
        Initialize ThreadExecutor.

        Args:
            max_workers: Maximum number of worker threads
            queue_size: Maximum queue size
            enable_priority: Enable priority queue
            default_timeout: Default task timeout
        """
        self.max_workers = max_workers
        self.queue_size = queue_size
        self.enable_priority = enable_priority
        self.default_timeout = default_timeout

        # Task management
        if enable_priority:
            self.task_queue = queue.PriorityQueue(maxsize=queue_size)
        else:
            self.task_queue = queue.Queue(maxsize=queue_size)

        self.active_tasks: Dict[str, Task] = {}
        self.completed_tasks: Dict[str, TaskResult] = {}
        self.futures: Dict[str, Future] = {}

        # Thread management
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="CallPyBack-Thread"
        )
        self.running = False
        self.workers: List[threading.Thread] = []
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)

        # Statistics
        self.stats = {
            "tasks_submitted": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_timeout": 0,
            "tasks_cancelled": 0,
            "total_execution_time": 0.0,
        }

        # Worker load tracking
        self.worker_load: Dict[str, int] = {}

    def start(self):
        """Start the executor."""
        with self.lock:
            if self.running:
                return

            self.running = True

            # Start dispatcher thread
            dispatcher = threading.Thread(
                target=self._dispatch_loop, name="TaskDispatcher", daemon=True
            )
            dispatcher.start()
            self.workers.append(dispatcher)

    def stop(self, wait: bool = True, timeout: float = 30.0):
        """Stop the executor."""
        with self.lock:
            if not self.running:
                return

            self.running = False

        # Cancel pending futures
        for future in self.futures.values():
            future.cancel()

        # Shutdown executor
        self.executor.shutdown(wait=False)

        if wait:
            done, pending = wait_for_futures(
                self.futures.values(), timeout=timeout, return_when=ALL_COMPLETED
            )
            for p in pending:
                p.cancel()
                logging.warning(f"Task {p} was cancelled")
            for p in done:
                p.result()

        # Wait for dispatcher
        for worker in self.workers:
            if worker.is_alive():
                worker.join(timeout=5.0)

    def submit(
        self,
        callable_obj: Union[Callable, CallPyBack],
        *args,
        priority: int = 0,
        timeout: Optional[float] = None,
        max_retries: int = 3,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> str:
        """
        Submit task for execution.

        Args:
            callable_obj: Function or CallPyBack to execute
            *args: Positional arguments
            priority: Task priority (higher = more important)
            timeout: Task timeout
            max_retries: Maximum retry attempts
            metadata: Additional metadata
            **kwargs: Keyword arguments

        Returns:
            Task ID
        """
        task = Task(
            callable=callable_obj,
            args=args,
            kwargs=kwargs,
            priority=priority,
            timeout=timeout or self.default_timeout,
            max_retries=max_retries,
            metadata=metadata or {},
        )

        try:
            self.task_queue.put(task, block=False)
            with self.lock:
                self.stats["tasks_submitted"] += 1
            return task.id
        except queue.Full:
            raise RuntimeError("Task queue is full")

    def submit_batch(self, tasks: List[Dict[str, Any]]) -> List[str]:
        """
        Submit multiple tasks at once.

        Args:
            tasks: List of task dictionaries

        Returns:
            List of task IDs
        """
        task_ids = []
        for task_config in tasks:
            callable_obj = task_config.pop("callable")
            task_id = self.submit(callable_obj, **task_config)
            task_ids.append(task_id)
        return task_ids

    def get_result(self, task_id: str, timeout: Optional[float] = None) -> TaskResult:
        """
        Get task result (blocking).

        Args:
            task_id: Task ID
            timeout: Wait timeout

        Returns:
            TaskResult
        """
        deadline = time.time() + timeout if timeout is not None else None

        # 1) wait for either registration in self.futures or an already‐completed result
        with self.cond:
            while task_id not in self.futures and task_id not in self.completed_tasks:
                if deadline is not None:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        raise TimeoutError(f"Task {task_id!r} never registered")
                else:
                    remaining = None
                self.cond.wait(timeout=remaining)

            # if it’s already done, return immediately
            if task_id in self.completed_tasks:
                return self.completed_tasks[task_id]
            future = self.futures[task_id]

        # 2) now wait on the Future itself for any remaining time
        try:
            rem = None if deadline is None else max(0, deadline - time.time())
            return future.result(timeout=rem)
        except Exception as e:
            return TaskResult(task_id=task_id, success=False, error=e)

    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a task.

        Args:
            task_id: Task ID to cancel

        Returns:
            True if cancelled successfully
        """
        with self.lock:
            if task_id in self.futures:
                future = self.futures[task_id]
                cancelled = future.cancel()
                if cancelled:
                    self.stats["tasks_cancelled"] += 1
                return cancelled
        return False

    def get_task_status(self, task_id: str) -> str:
        """Get task status."""
        if task_id in self.completed_tasks:
            return "completed"
        elif task_id in self.active_tasks:
            return "running"
        elif task_id in self.futures:
            future = self.futures[task_id]
            if future.cancelled():
                return "cancelled"
            elif future.running():
                return "running"
            else:
                return "pending"
        else:
            return "unknown"

    def list_active_tasks(self) -> List[Task]:
        """List currently active tasks."""
        with self.lock:
            return list(self.active_tasks.values())

    def wait_for_completion(
        self, task_ids: Optional[List[str]] = None, timeout: Optional[float] = None
    ) -> Dict[str, TaskResult]:
        """
        Wait for tasks to complete.

        Args:
            task_ids: Specific task IDs to wait for (None = all)
            timeout: Overall timeout

        Returns:
            Dictionary of task_id -> TaskResult
        """
        if task_ids is None:
            # Wait for all pending futures
            futures_to_wait = list(self.futures.values())
        else:
            futures_to_wait = [
                self.futures[tid] for tid in task_ids if tid in self.futures
            ]

        results = {}

        try:
            for future in as_completed(futures_to_wait, timeout=timeout):
                # Find task_id for this future
                task_id = None
                for tid, fut in self.futures.items():
                    if fut == future:
                        task_id = tid
                        break

                if task_id:
                    try:
                        result = future.result()
                        results[task_id] = result
                    except Exception as e:
                        results[task_id] = TaskResult(
                            task_id=task_id, success=False, error=e
                        )

        except Exception as e:
            # Handle timeout or other errors
            pass

        return results

    def _dispatch_loop(self):
        """Main dispatcher loop."""
        while self.running:
            try:
                # Get next task
                try:
                    task = self.task_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                # Submit to thread pool
                future = self.executor.submit(self._execute_task, task)

                with self.cond:
                    self.futures[task.id] = future
                    self.active_tasks[task.id] = task
                    self.cond.notify_all()

                # Add completion callback
                future.add_done_callback(
                    lambda fut, tid=task.id: self._task_completed(tid, fut)
                )

            except Exception as e:
                # Log error and continue

                logging.error(f"Dispatcher error: {e}")
                time.sleep(0.1)

    def _execute_task(self, task: Task) -> TaskResult:
        """Execute a single task."""
        worker_id = threading.current_thread().name
        start_time = time.time()

        # Update worker load
        with self.lock:
            self.worker_load[worker_id] = self.worker_load.get(worker_id, 0) + 1

        try:
            task.started_at = start_time

            # Execute the callable
            if isinstance(task.callable, CallPyBack):
                # CallPyBack wrapped function
                result = task.callable(*task.args, **task.kwargs)
            else:
                # Regular function
                result = task.callable(*task.args, **task.kwargs)

            execution_time = time.time() - start_time
            task.completed_at = time.time()

            return TaskResult(
                task_id=task.id,
                success=True,
                result=result,
                execution_time=execution_time,
                worker_id=worker_id,
                metadata=task.metadata,
            )

        except Exception as e:
            execution_time = time.time() - start_time

            return TaskResult(
                task_id=task.id,
                success=False,
                error=e,
                execution_time=execution_time,
                worker_id=worker_id,
                metadata=task.metadata,
            )

        finally:
            # Update worker load
            with self.lock:
                self.worker_load[worker_id] -= 1

    def _task_completed(self, task_id: str, future: Future):
        """Handle task completion."""
        try:
            result = future.result()
        except Exception as e:
            result = TaskResult(task_id=task_id, success=False, error=e)

            # Move from in-flight → completed, and notify waiters
            with self.cond:
                self.completed_tasks[task_id] = result
                self.active_tasks.pop(task_id, None)
                self.futures.pop(task_id, None)
                self.cond.notify_all()

            # Update statistics
            if result.success:
                self.stats["tasks_completed"] += 1
            else:
                self.stats["tasks_failed"] += 1

            self.stats["total_execution_time"] += result.execution_time

    def get_stats(self) -> Dict[str, Any]:
        """Get executor statistics."""
        with self.lock:
            return {
                **self.stats,
                "active_tasks": len(self.active_tasks),
                "pending_tasks": self.task_queue.qsize(),
                "completed_tasks": len(self.completed_tasks),
                "worker_load": dict(self.worker_load),
                "max_workers": self.max_workers,
                "avg_execution_time": (
                    self.stats["total_execution_time"]
                    / max(self.stats["tasks_completed"], 1)
                ),
            }

    def cleanup_completed_tasks(self, keep_count: int = 1000):
        """Clean up old completed tasks to manage memory."""
        with self.lock:
            if len(self.completed_tasks) <= keep_count:
                return

            # Sort by completion time and keep most recent
            sorted_tasks = sorted(
                self.completed_tasks.items(),
                key=lambda x: x[1].metadata.get("completed_at", 0),
                reverse=True,
            )

            # Keep only the most recent tasks
            self.completed_tasks = dict(sorted_tasks[:keep_count])
