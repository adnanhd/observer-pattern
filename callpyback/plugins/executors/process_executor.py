"""
Process-based executor for CPU-intensive parallel task execution.
Provides process pool management with inter-process communication.
"""

import logging
import multiprocessing as mp
import pickle
import time
from concurrent.futures import ALL_COMPLETED, Future, ProcessPoolExecutor, as_completed
from concurrent.futures import wait as wait_for_futures
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from callpyback import CallPyBack


@dataclass
class ProcessTask:
    """Task container for process execution."""

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

    def __lt__(self, other):
        """Priority queue ordering."""
        return self.priority > other.priority

    def serialize(self) -> bytes:
        """Serialize task for inter-process communication."""
        return pickle.dumps(self)

    @classmethod
    def deserialize(cls, data: bytes) -> "ProcessTask":
        """Deserialize task from bytes."""
        return pickle.loads(data)


@dataclass
class ProcessResult:
    """Process execution result."""

    task_id: str
    success: bool
    result: Any = None
    error: Optional[str] = None  # Serialized exception
    execution_time: float = 0.0
    process_id: int = 0
    memory_usage: Optional[float] = None
    cpu_time: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def execute_task_in_process(task_data: bytes) -> ProcessResult:
    """
    Execute task in separate process.
    This function will be pickled and sent to worker processes.
    """
    import os
    import time
    import traceback

    import psutil

    try:
        # Deserialize task
        task = ProcessTask.deserialize(task_data)

        # Get process info
        process = psutil.Process(os.getpid())
        start_memory = process.memory_info().rss / 1024 / 1024  # MB
        start_time = time.time()
        start_cpu = process.cpu_percent()

        # Execute the callable
        if hasattr(task.callable, "__call__"):
            # Handle both regular functions and CallPyBack instances
            result = task.callable(*task.args, **task.kwargs)
        else:
            raise TypeError(f"Task callable is not callable: {type(task.callable)}")

        # Measure resource usage
        end_time = time.time()
        end_memory = process.memory_info().rss / 1024 / 1024  # MB
        execution_time = end_time - start_time
        cpu_time = process.cpu_percent()

        return ProcessResult(
            task_id=task.id,
            success=True,
            result=result,
            execution_time=execution_time,
            process_id=os.getpid(),
            memory_usage=end_memory - start_memory,
            cpu_time=cpu_time,
            metadata=task.metadata,
        )

    except Exception as e:
        return ProcessResult(
            task_id=task.id,
            success=False,
            error=f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}",
            execution_time=time.time() - start_time if "start_time" in locals() else 0,
            process_id=os.getpid(),
            metadata=task.metadata,
        )


class ProcessExecutor:
    """
    Advanced process-based executor for CPU-intensive tasks.

    Features:
    - Process pool management
    - Inter-process communication
    - Resource usage monitoring
    - Task serialization/deserialization
    - Memory and CPU tracking
    - Process health monitoring
    """

    def __init__(
        self,
        max_workers: Optional[int] = None,
        queue_size: int = 1000,
        enable_monitoring: bool = True,
        process_timeout: float = 300.0,
    ):
        """
        Initialize ProcessExecutor.

        Args:
            max_workers: Maximum number of worker processes (default: CPU count)
            queue_size: Maximum queue size
            enable_monitoring: Enable resource monitoring
            process_timeout: Default process timeout
        """
        self.max_workers = max_workers or mp.cpu_count()
        self.queue_size = queue_size
        self.enable_monitoring = enable_monitoring
        self.process_timeout = process_timeout

        # Task management
        self.manager = mp.Manager()
        self.task_queue = mp.Queue(maxsize=queue_size)
        self.result_queue = mp.Queue()
        self.active_tasks: Dict[str, ProcessTask] = {}
        self.completed_tasks: Dict[str, ProcessResult] = {}
        self.futures: Dict[str, Future] = {}

        # Process management
        self.executor = ProcessPoolExecutor(max_workers=self.max_workers)
        self.worker_processes: List[mp.Process] = []
        self.running = False
        self.lock = mp.RLock()
        self.cond = mp.Condition(self.lock)

        # Statistics
        self.stats = {
            "tasks_submitted": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_timeout": 0,
            "total_execution_time": 0.0,
            "total_memory_usage": 0.0,
            "total_cpu_time": 0.0,
        }

        # Resource monitoring
        if enable_monitoring:
            self.process_monitor = self.manager.dict()

    def start(self):
        """Start the process executor."""
        if self.running:
            return

        self.running = True

        # Start result collector thread
        import threading

        collector = threading.Thread(
            target=self._collect_results, name="ProcessResultCollector", daemon=True
        )
        collector.start()

    def stop(self, wait: bool = True, timeout: float = 30.0):
        """Stop the process executor."""
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

        # Terminate worker processes if needed
        for process in self.worker_processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5.0)

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
        Submit task for process execution.

        Args:
            callable_obj: Function or CallPyBack to execute
            *args: Positional arguments
            priority: Task priority
            timeout: Task timeout
            max_retries: Maximum retry attempts
            metadata: Additional metadata
            **kwargs: Keyword arguments

        Returns:
            Task ID
        """
        # Validate callable can be pickled
        try:
            pickle.dumps(callable_obj)
        except Exception as e:
            raise ValueError(f"Callable cannot be pickled: {e}")

        task = ProcessTask(
            callable=callable_obj,
            args=args,
            kwargs=kwargs,
            priority=priority,
            timeout=timeout or self.process_timeout,
            max_retries=max_retries,
            metadata=metadata or {},
        )

        # Submit to process pool
        try:
            task_data = task.serialize()
            future = self.executor.submit(execute_task_in_process, task_data)

            with self.cond:
                self.active_tasks[task.id] = task
                self.futures[task.id] = future
                self.stats["tasks_submitted"] += 1
                self.cond.notify_all()

            return task.id

        except Exception as e:
            raise RuntimeError(f"Failed to submit task: {e}")

    def submit_batch(self, tasks: List[Dict[str, Any]]) -> List[str]:
        """Submit multiple tasks for batch processing."""
        task_ids = []
        for task_config in tasks:
            callable_obj = task_config.pop("callable")
            task_id = self.submit(callable_obj, **task_config)
            task_ids.append(task_id)
        return task_ids

    def get_result(
        self, task_id: str, timeout: Optional[float] = None
    ) -> ProcessResult:
        """Get task result (blocking)."""
        deadline = time.time() + timeout if timeout is not None else None

        # 1) wait until the task is registered or already done
        with self.cond:
            while task_id not in self.futures and task_id not in self.completed_tasks:
                if deadline is not None and time.time() >= deadline:
                    raise TimeoutError(f"Task {task_id!r} never registered")
                remaining = None if deadline is None else (deadline - time.time())
                self.cond.wait(timeout=remaining)

            if task_id in self.completed_tasks:
                return self.completed_tasks[task_id]

            future = self.futures[task_id]

        # 2) wait for the Future itself
        try:
            rem = None if deadline is None else max(0, deadline - time.time())
            return future.result(timeout=rem)
        except Exception as e:
            return ProcessResult(task_id=task_id, success=False, error=str(e))

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        if task_id in self.futures:
            future = self.futures[task_id]
            cancelled = future.cancel()
            if cancelled:
                self.stats["tasks_cancelled"] = self.stats.get("tasks_cancelled", 0) + 1
            return cancelled
        return False

    def get_task_status(self, task_id: str) -> str:
        """Get task status."""
        if task_id in self.completed_tasks:
            return "completed"
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

    def wait_for_completion(
        self, task_ids: Optional[List[str]] = None, timeout: Optional[float] = None
    ) -> Dict[str, ProcessResult]:
        """Wait for tasks to complete."""
        if task_ids is None:
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
                        self.completed_tasks[task_id] = result
                    except Exception as e:
                        results[task_id] = ProcessResult(
                            task_id=task_id, success=False, error=str(e)
                        )

        except Exception:
            pass

        return results

    def _collect_results(self):
        """Collect results from completed futures."""
        while self.running:
            try:
                completed_futures = []

                for task_id, future in list(self.futures.items()):
                    if future.done():
                        completed_futures.append((task_id, future))

                for task_id, future in completed_futures:
                    try:
                        result = future.result()
                        self._process_completed_task(task_id, result)
                    except Exception as e:
                        result = ProcessResult(
                            task_id=task_id, success=False, error=str(e)
                        )
                        self._process_completed_task(task_id, result)

                time.sleep(0.1)  # Brief pause

            except Exception as e:
                logging.error(f"Result collector error: {e}")
                time.sleep(1.0)

    def _process_completed_task(self, task_id: str, result: ProcessResult):
        """Process completed task result."""
        # Move to completed tasks
        with self.cond:
            self.completed_tasks[task_id] = result
            self.active_tasks.pop(task_id, None)
            self.futures.pop(task_id, None)

        # Update statistics
        if result.success:
            self.stats["tasks_completed"] += 1
        else:
            self.stats["tasks_failed"] += 1

        self.stats["total_execution_time"] += result.execution_time

        if result.memory_usage:
            self.stats["total_memory_usage"] += result.memory_usage

        if result.cpu_time:
            self.stats["total_cpu_time"] += result.cpu_time

        self.cond.notify_all()

    def get_stats(self) -> Dict[str, Any]:
        """Get executor statistics."""
        completed_count = max(self.stats["tasks_completed"], 1)

        stats = {
            **self.stats,
            "active_tasks": len(self.active_tasks),
            "completed_tasks": len(self.completed_tasks),
            "max_workers": self.max_workers,
            "avg_execution_time": self.stats["total_execution_time"] / completed_count,
            "avg_memory_usage": self.stats["total_memory_usage"] / completed_count,
            "avg_cpu_time": self.stats["total_cpu_time"] / completed_count,
        }

        return stats

    def get_resource_usage(self) -> Dict[str, Any]:
        """Get current resource usage."""
        if not self.enable_monitoring:
            return {}

        try:
            import psutil

            process = psutil.Process()

            return {
                "memory_percent": process.memory_percent(),
                "cpu_percent": process.cpu_percent(),
                "num_threads": process.num_threads(),
                "open_files": len(process.open_files()),
                "children_count": len(process.children()),
            }
        except Exception:
            return {}

    def scale_workers(self, new_worker_count: int):
        """Dynamically scale the number of workers."""
        if new_worker_count <= 0:
            raise ValueError("Worker count must be positive")

        if new_worker_count == self.max_workers:
            return

        # Create new executor with updated worker count
        old_executor = self.executor
        self.executor = ProcessPoolExecutor(max_workers=new_worker_count)
        self.max_workers = new_worker_count

        # Shutdown old executor
        old_executor.shutdown(wait=False)

    def cleanup_completed_tasks(self, keep_count: int = 1000):
        """Clean up old completed tasks to manage memory."""
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
