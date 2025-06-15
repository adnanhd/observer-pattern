"""
Hybrid executor that intelligently chooses between thread and process execution.
Provides optimal performance by routing tasks to the most appropriate executor.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from callpyback import CallPyBack
from callpyback.plugins.executors.thread_executor import ThreadExecutor, TaskResult
from callpyback.plugins.executors.process_executor import ProcessExecutor, ProcessResult


@dataclass
class ExecutionStrategy:
    """Configuration for execution strategy selection."""

    # CPU-bound indicators
    cpu_bound_keywords: List[str] = field(
        default_factory=lambda: [
            "compute",
            "calculate",
            "process",
            "algorithm",
            "math",
            "crypto",
            "encode",
            "decode",
            "compress",
            "parse",
            "transform",
        ]
    )

    # I/O-bound indicators
    io_bound_keywords: List[str] = field(
        default_factory=lambda: [
            "fetch",
            "download",
            "upload",
            "request",
            "query",
            "save",
            "load",
            "read",
            "write",
            "api",
            "database",
            "file",
        ]
    )

    # Thresholds
    cpu_bound_threshold: float = 0.1  # seconds of expected CPU time
    memory_threshold: int = 100  # MB of expected memory usage
    io_wait_threshold: float = 0.5  # seconds of expected I/O wait

    # Default strategies
    default_thread_strategy: bool = True  # Use threads by default
    force_process_for_callpyback: bool = False


class TaskClassifier:
    """Classifies tasks to determine optimal execution strategy."""

    def __init__(self, strategy: ExecutionStrategy):
        self.strategy = strategy
        self.execution_history: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.RLock()

    def classify_task(
        self,
        callable_obj: Union[Callable, CallPyBack],
        args: tuple,
        kwargs: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> str:
        """
        Classify task as 'thread' or 'process'.

        Args:
            callable_obj: Function to execute
            args: Function arguments
            kwargs: Function keyword arguments
            metadata: Task metadata

        Returns:
            'thread' or 'process'
        """
        # Check explicit hint in metadata
        if "execution_strategy" in metadata:
            strategy = metadata["execution_strategy"]
            if strategy in ["thread", "process"]:
                return strategy

        # Check function name and docstring for hints
        func_name = getattr(callable_obj, "__name__", "")
        func_doc = getattr(callable_obj, "__doc__", "") or ""

        # CPU-bound indicators
        if self._contains_keywords(
            func_name + " " + func_doc, self.strategy.cpu_bound_keywords
        ):
            return "process"

        # I/O-bound indicators
        if self._contains_keywords(
            func_name + " " + func_doc, self.strategy.io_bound_keywords
        ):
            return "thread"

        # Check historical performance
        if func_name in self.execution_history:
            history = self.execution_history[func_name]
            avg_cpu_time = history.get("avg_cpu_time", 0)
            avg_memory = history.get("avg_memory", 0)

            if avg_cpu_time > self.strategy.cpu_bound_threshold:
                return "process"

            if avg_memory > self.strategy.memory_threshold:
                return "process"

        # Check for CallPyBack instances
        if isinstance(callable_obj, CallPyBack):
            if self.strategy.force_process_for_callpyback:
                return "process"

        # Check argument complexity (heuristic)
        if self._has_complex_data(args, kwargs):
            return "process"

        # Default strategy
        return "thread" if self.strategy.default_thread_strategy else "process"

    def update_history(
        self,
        func_name: str,
        execution_time: float,
        cpu_time: float = 0,
        memory_usage: float = 0,
        strategy_used: str = "thread",
    ):
        """Update execution history for learning."""
        with self.lock:
            if func_name not in self.execution_history:
                self.execution_history[func_name] = {
                    "executions": 0,
                    "total_time": 0,
                    "total_cpu_time": 0,
                    "total_memory": 0,
                    "thread_count": 0,
                    "process_count": 0,
                }

            history = self.execution_history[func_name]
            history["executions"] += 1
            history["total_time"] += execution_time
            history["total_cpu_time"] += cpu_time
            history["total_memory"] += memory_usage

            if strategy_used == "thread":
                history["thread_count"] += 1
            else:
                history["process_count"] += 1

            # Update averages
            count = history["executions"]
            history["avg_time"] = history["total_time"] / count
            history["avg_cpu_time"] = history["total_cpu_time"] / count
            history["avg_memory"] = history["total_memory"] / count

    def _contains_keywords(self, text: str, keywords: List[str]) -> bool:
        """Check if text contains any of the keywords."""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in keywords)

    def _has_complex_data(self, args: tuple, kwargs: Dict[str, Any]) -> bool:
        """Heuristic to detect complex data structures."""

        def is_complex(obj):
            if isinstance(obj, (list, tuple)) and len(obj) > 1000:
                return True
            if isinstance(obj, dict) and len(obj) > 100:
                return True
            if isinstance(obj, str) and len(obj) > 10000:
                return True
            return False

        for arg in args:
            if is_complex(arg):
                return True

        for value in kwargs.values():
            if is_complex(value):
                return True

        return False


class HybridExecutor:
    """
    Hybrid executor that intelligently routes tasks between thread and process execution.

    Features:
    - Automatic strategy selection
    - Performance-based learning
    - Load balancing between executors
    - Unified task management
    - Resource optimization
    - Execution monitoring
    """

    def __init__(
        self,
        max_threads: int = 4,
        max_processes: Optional[int] = None,
        strategy: Optional[ExecutionStrategy] = None,
        enable_learning: bool = True,
    ):
        """
        Initialize HybridExecutor.

        Args:
            max_threads: Maximum thread workers
            max_processes: Maximum process workers
            strategy: Execution strategy configuration
            enable_learning: Enable performance learning
        """
        self.max_threads = max_threads
        self.max_processes = max_processes
        self.strategy = strategy or ExecutionStrategy()
        self.enable_learning = enable_learning

        # Executors
        self.thread_executor = ThreadExecutor(max_workers=max_threads)
        self.process_executor = ProcessExecutor(max_workers=max_processes)

        # Task classification
        self.classifier = TaskClassifier(self.strategy)

        # Task tracking
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.RLock()

        # Statistics
        self.stats = {
            "total_tasks": 0,
            "thread_tasks": 0,
            "process_tasks": 0,
            "classification_accuracy": 0.0,
        }

    def start(self):
        """Start both executors."""
        self.thread_executor.start()
        self.process_executor.start()

    def stop(self, wait: bool = True, timeout: float = 30.0):
        """Stop both executors."""
        self.thread_executor.stop(wait=wait, timeout=timeout)
        self.process_executor.stop(wait=wait, timeout=timeout)

    def submit(
        self,
        callable_obj: Union[Callable, CallPyBack],
        *args,
        priority: int = 0,
        timeout: Optional[float] = None,
        max_retries: int = 3,
        force_strategy: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> str:
        """
        Submit task with automatic strategy selection.

        Args:
            callable_obj: Function or CallPyBack to execute
            *args: Positional arguments
            priority: Task priority
            timeout: Task timeout
            max_retries: Maximum retry attempts
            force_strategy: Force 'thread' or 'process' strategy
            metadata: Additional metadata
            **kwargs: Keyword arguments

        Returns:
            Task ID
        """
        task_id = str(uuid4())
        task_metadata = metadata or {}

        # Determine execution strategy
        if force_strategy:
            strategy = force_strategy
        else:
            strategy = self.classifier.classify_task(
                callable_obj, args, kwargs, task_metadata
            )

        # Track task
        with self.lock:
            self.tasks[task_id] = {
                "strategy": strategy,
                "func_name": getattr(callable_obj, "__name__", "unknown"),
                "submitted_at": time.time(),
                "priority": priority,
                "metadata": task_metadata,
            }

            self.stats["total_tasks"] += 1
            if strategy == "thread":
                self.stats["thread_tasks"] += 1
            else:
                self.stats["process_tasks"] += 1

        # Submit to appropriate executor
        if strategy == "thread":
            executor_task_id = self.thread_executor.submit(
                callable_obj,
                *args,
                priority=priority,
                timeout=timeout,
                max_retries=max_retries,
                metadata=task_metadata,
                **kwargs,
            )
        else:
            executor_task_id = self.process_executor.submit(
                callable_obj,
                *args,
                priority=priority,
                timeout=timeout,
                max_retries=max_retries,
                metadata=task_metadata,
                **kwargs,
            )

        # Link task IDs
        with self.lock:
            self.tasks[task_id]["executor_task_id"] = executor_task_id

        return task_id

    def submit_batch(self, tasks: List[Dict[str, Any]]) -> List[str]:
        """Submit multiple tasks with automatic load balancing."""
        task_ids = []

        # Group tasks by strategy for efficient batching
        thread_tasks = []
        process_tasks = []

        for task_config in tasks:
            callable_obj = task_config["callable"]
            metadata = task_config.get("metadata", {})

            strategy = self.classifier.classify_task(
                callable_obj,
                task_config.get("args", ()),
                task_config.get("kwargs", {}),
                metadata,
            )

            if strategy == "thread":
                thread_tasks.append(task_config)
            else:
                process_tasks.append(task_config)

        # Submit batches
        if thread_tasks:
            thread_ids = self.thread_executor.submit_batch(thread_tasks)
            task_ids.extend(thread_ids)

        if process_tasks:
            process_ids = self.process_executor.submit_batch(process_tasks)
            task_ids.extend(process_ids)

        return task_ids

    def get_result(
        self, task_id: str, timeout: Optional[float] = None
    ) -> Union[TaskResult, ProcessResult]:
        """Get task result from appropriate executor."""
        task_info = self.tasks.get(task_id)
        if not task_info:
            raise ValueError(f"Task {task_id} not found")

        executor_task_id = task_info["executor_task_id"]
        strategy = task_info["strategy"]

        # Get result from appropriate executor
        if strategy == "thread":
            result = self.thread_executor.get_result(executor_task_id, timeout)
        else:
            result = self.process_executor.get_result(executor_task_id, timeout)

        # Update learning if enabled
        if self.enable_learning and result.success:
            self.classifier.update_history(
                task_info["func_name"],
                result.execution_time,
                getattr(result, "cpu_time", 0),
                getattr(result, "memory_usage", 0),
                strategy,
            )

        return result

    def cancel_task(self, task_id: str) -> bool:
        """Cancel task in appropriate executor."""
        task_info = self.tasks.get(task_id)
        if not task_info:
            return False

        executor_task_id = task_info["executor_task_id"]
        strategy = task_info["strategy"]

        if strategy == "thread":
            return self.thread_executor.cancel_task(executor_task_id)
        else:
            return self.process_executor.cancel_task(executor_task_id)

    def get_task_status(self, task_id: str) -> str:
        """Get task status from appropriate executor."""
        task_info = self.tasks.get(task_id)
        if not task_info:
            return "unknown"

        executor_task_id = task_info["executor_task_id"]
        strategy = task_info["strategy"]

        if strategy == "thread":
            return self.thread_executor.get_task_status(executor_task_id)
        else:
            return self.process_executor.get_task_status(executor_task_id)

    def wait_for_completion(
        self, task_ids: Optional[List[str]] = None, timeout: Optional[float] = None
    ) -> Dict[str, Union[TaskResult, ProcessResult]]:
        """Wait for tasks to complete."""
        if task_ids is None:
            task_ids = list(self.tasks.keys())

        results = {}
        for task_id in task_ids:
            try:
                result = self.get_result(task_id, timeout)
                results[task_id] = result
            except Exception as e:
                # Handle timeout or other errors
                continue

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics."""
        thread_stats = self.thread_executor.get_stats()
        process_stats = self.process_executor.get_stats()

        # Calculate classification accuracy (if we have enough history)
        accuracy = self._calculate_classification_accuracy()

        return {
            **self.stats,
            "classification_accuracy": accuracy,
            "thread_executor": thread_stats,
            "process_executor": process_stats,
            "total_active_tasks": (
                thread_stats.get("active_tasks", 0)
                + process_stats.get("active_tasks", 0)
            ),
            "execution_history_size": len(self.classifier.execution_history),
        }

    def _calculate_classification_accuracy(self) -> float:
        """Calculate classification accuracy based on performance."""
        if not self.enable_learning:
            return 0.0

        history = self.classifier.execution_history
        if not history:
            return 0.0

        total_accuracy = 0.0
        total_functions = 0

        for func_name, data in history.items():
            thread_count = data.get("thread_count", 0)
            process_count = data.get("process_count", 0)
            total_count = thread_count + process_count

            if total_count == 0:
                continue

            # Simple heuristic: if mostly used one strategy, assume it's optimal
            if thread_count > process_count:
                accuracy = thread_count / total_count
            else:
                accuracy = process_count / total_count

            total_accuracy += accuracy
            total_functions += 1

        return total_accuracy / max(total_functions, 1)

    def optimize_strategy(self) -> Dict[str, Any]:
        """Analyze and optimize execution strategy."""
        if not self.enable_learning:
            return {"message": "Learning disabled"}

        history = self.classifier.execution_history
        recommendations = []

        for func_name, data in history.items():
            thread_count = data.get("thread_count", 0)
            process_count = data.get("process_count", 0)
            avg_time = data.get("avg_time", 0)
            avg_cpu_time = data.get("avg_cpu_time", 0)
            avg_memory = data.get("avg_memory", 0)

            # Analyze performance patterns
            if (
                avg_cpu_time > self.strategy.cpu_bound_threshold
                and thread_count > process_count
            ):
                recommendations.append(
                    {
                        "function": func_name,
                        "current": "mostly_thread",
                        "recommended": "process",
                        "reason": f"High CPU usage ({avg_cpu_time:.3f}s)",
                    }
                )

            if (
                avg_memory > self.strategy.memory_threshold
                and thread_count > process_count
            ):
                recommendations.append(
                    {
                        "function": func_name,
                        "current": "mostly_thread",
                        "recommended": "process",
                        "reason": f"High memory usage ({avg_memory:.1f}MB)",
                    }
                )

        return {
            "total_functions_analyzed": len(history),
            "recommendations": recommendations,
            "strategy_distribution": {
                "thread_preference": sum(
                    1
                    for d in history.values()
                    if d.get("thread_count", 0) > d.get("process_count", 0)
                ),
                "process_preference": sum(
                    1
                    for d in history.values()
                    if d.get("process_count", 0) > d.get("thread_count", 0)
                ),
            },
        }

    def set_strategy(self, new_strategy: ExecutionStrategy):
        """Update execution strategy."""
        self.strategy = new_strategy
        self.classifier.strategy = new_strategy

    def clear_history(self):
        """Clear execution history."""
        with self.lock:
            self.classifier.execution_history.clear()
