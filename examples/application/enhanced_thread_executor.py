#!/usr/bin/env python3
"""
Provides user-friendly decorators and fluent API
"""

import functools
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

from callpyback.plugins.executors.thread_executor import Task
from callpyback.plugins.executors.thread_executor import (
    ThreadExecutor as BaseThreadExecutor,
)

T = TypeVar("T")


@dataclass
class TaskBuilder:
    """Fluent API for building tasks"""

    callable_fn: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    timeout: Optional[float] = None
    max_retries: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)

    def with_args(self, *args) -> "TaskBuilder":
        """Set task arguments"""
        self.args = args
        return self

    def with_kwargs(self, **kwargs) -> "TaskBuilder":
        """Set task keyword arguments"""
        self.kwargs = kwargs
        return self

    def with_priority(self, priority: int) -> "TaskBuilder":
        """Set task priority (higher = more important)"""
        self.priority = priority
        return self

    def with_timeout(self, timeout: float) -> "TaskBuilder":
        """Set task timeout"""
        self.timeout = timeout
        return self

    def with_retries(self, max_retries: int) -> "TaskBuilder":
        """Set maximum retry attempts"""
        self.max_retries = max_retries
        return self

    def with_metadata(self, **metadata) -> "TaskBuilder":
        """Add metadata to task"""
        self.metadata.update(metadata)
        return self

    def build(self) -> Task:
        """Build the final task"""
        return Task(
            callable=self.callable_fn,
            args=self.args,
            kwargs=self.kwargs,
            priority=self.priority,
            timeout=self.timeout,
            max_retries=self.max_retries,
            metadata=self.metadata,
        )


class AsyncResult(Generic[T]):
    """Enhanced async result with fluent API"""

    def __init__(self, task_id: str, executor: "EnhancedThreadExecutor"):
        self.task_id = task_id
        self.executor = executor
        self._result: Optional[T] = None
        self._exception: Optional[Exception] = None
        self._completed = False

    def get(self, timeout: Optional[float] = None) -> T:
        """Get result with optional timeout"""
        try:
            result = self.executor.get_result(self.task_id, timeout=timeout)
            return result.result
        except Exception as e:
            raise e

    def then(self, callback: Callable[[T], Any]) -> "AsyncResult":
        """Chain callback on success"""

        def wrapper():
            try:
                result = self.get()
                return callback(result)
            except Exception:
                return None

        task_id = self.executor.submit(wrapper)
        return AsyncResult(task_id, self.executor)

    def catch(self, error_handler: Callable[[Exception], Any]) -> "AsyncResult":
        """Handle errors"""

        def wrapper():
            try:
                return self.get()
            except Exception as e:
                return error_handler(e)

        task_id = self.executor.submit(wrapper)
        return AsyncResult(task_id, self.executor)

    def is_done(self) -> bool:
        """Check if task is completed"""
        return self.executor.is_completed(self.task_id)


class EnhancedThreadExecutor(BaseThreadExecutor):
    """Enhanced ThreadExecutor with syntactic sugar"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._task_decorators = {}

    # Fluent API methods
    def task(
        self,
        func: Callable = None,
        *,
        priority: int = 0,
        timeout: float = None,
        retries: int = 3,
    ):
        """Decorator to register a function as a task"""

        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                return self.submit(
                    fn,
                    *args,
                    priority=priority,
                    timeout=timeout,
                    max_retries=retries,
                    **kwargs,
                )

            # Store original function
            wrapper._original = fn
            wrapper._task_config = {
                "priority": priority,
                "timeout": timeout,
                "retries": retries,
            }

            return wrapper

        if func is None:
            return decorator
        else:
            return decorator(func)

    def parallel(self, *functions: Callable) -> List[AsyncResult]:
        """Execute multiple functions in parallel"""
        results = []
        for func in functions:
            if hasattr(func, "_original"):
                # It's a decorated task
                config = func._task_config
                task_id = self.submit(
                    func._original,
                    priority=config["priority"],
                    timeout=config["timeout"],
                    max_retries=config["retries"],
                )
            else:
                task_id = self.submit(func)

            results.append(AsyncResult(task_id, self))

        return results

    def map(
        self, func: Callable, items: List[Any], **task_options
    ) -> List[AsyncResult]:
        """Map function over list of items in parallel"""
        results = []
        for item in items:
            task_id = self.submit(func, item, **task_options)
            results.append(AsyncResult(task_id, self))

        return results

    def gather(self, *async_results: AsyncResult, timeout: float = None) -> List[Any]:
        """Gather results from multiple AsyncResult objects"""
        results = []
        for async_result in async_results:
            try:
                result = async_result.get(timeout=timeout)
                results.append(result)
            except Exception as e:
                results.append(e)

        return results

    def submit(self, callable_obj: Callable, *args, **kwargs) -> str:
        """Enhanced submit with better defaults"""

        # Extract task options from kwargs
        priority = kwargs.pop("priority", 0)
        timeout = kwargs.pop("timeout", self.default_timeout)
        max_retries = kwargs.pop("max_retries", 3)
        metadata = kwargs.pop("metadata", {})

        task = Task(
            callable=callable_obj,
            args=args,
            kwargs=kwargs,
            priority=priority,
            timeout=timeout,
            max_retries=max_retries,
            metadata=metadata,
        )

        return self.submit_task(task)

    def submit_async(self, callable_obj: Callable, *args, **kwargs) -> AsyncResult:
        """Submit task and return AsyncResult"""
        task_id = self.submit(callable_obj, *args, **kwargs)
        return AsyncResult(task_id, self)

    def create_task(self, func: Callable) -> TaskBuilder:
        """Create a task builder for fluent API"""
        return TaskBuilder(func)

    # Batch operations
    def submit_batch(self, tasks: List[TaskBuilder]) -> List[AsyncResult]:
        """Submit multiple tasks as a batch"""
        results = []
        for task_builder in tasks:
            task = task_builder.build()
            task_id = self.submit_task(task)
            results.append(AsyncResult(task_id, self))

        return results

    def wait_for_all(
        self, async_results: List[AsyncResult], timeout: float = None
    ) -> List[Any]:
        """Wait for all async results to complete"""
        return self.gather(*async_results, timeout=timeout)

    def wait_for_any(
        self, async_results: List[AsyncResult], timeout: float = None
    ) -> Any:
        """Wait for any async result to complete (first one wins)"""

        completed = []
        start_time = time.time()

        while not completed and (
            timeout is None or (time.time() - start_time) < timeout
        ):
            for async_result in async_results:
                if async_result.is_done():
                    try:
                        return async_result.get()
                    except Exception as e:
                        # Continue to next result if this one failed
                        continue

            time.sleep(0.01)  # Small delay to prevent busy waiting

        raise TimeoutError("No task completed within timeout")

    # Context manager support
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


# Convenience functions for global executor
_global_executor: Optional[EnhancedThreadExecutor] = None


def get_global_executor() -> EnhancedThreadExecutor:
    """Get or create global executor instance"""
    global _global_executor
    if _global_executor is None:
        _global_executor = EnhancedThreadExecutor()
        _global_executor.start()
    return _global_executor


def async_task(priority: int = 0, timeout: float = None, retries: int = 3):
    """Global decorator for async tasks"""

    def decorator(func: Callable) -> Callable:
        executor = get_global_executor()
        return executor.task(func, priority=priority, timeout=timeout, retries=retries)

    return decorator


def run_parallel(*functions: Callable) -> List[Any]:
    """Run functions in parallel using global executor"""
    executor = get_global_executor()
    async_results = executor.parallel(*functions)
    return executor.gather(*async_results)


def map_parallel(func: Callable, items: List[Any], **options) -> List[Any]:
    """Map function over items in parallel using global executor"""
    executor = get_global_executor()
    async_results = executor.map(func, items, **options)
    return executor.gather(*async_results)


# Example usage demonstration
if __name__ == "__main__":

    # Example 1: Using decorators
    @async_task(priority=1, timeout=5.0)
    def cpu_intensive_task(n: int) -> int:
        """Simulate CPU intensive work"""
        time.sleep(0.1)
        return sum(range(n))

    @async_task(priority=2)
    def io_task(delay: float) -> str:
        """Simulate I/O work"""
        time.sleep(delay)
        return f"Completed after {delay}s"

    # Example 2: Using enhanced executor directly
    with EnhancedThreadExecutor(max_workers=4) as executor:

        # Fluent task building
        task1 = (
            executor.create_task(cpu_intensive_task)
            .with_args(1000)
            .with_priority(2)
            .with_timeout(10.0)
            .with_metadata(description="Heavy computation")
        )

        # Submit and get async result
        result1 = executor.submit_async(cpu_intensive_task, 500)
        result2 = executor.submit_async(io_task, 0.2)

        # Parallel execution
        parallel_results = executor.parallel(
            lambda: cpu_intensive_task(100), lambda: io_task(0.1), lambda: "Simple task"
        )

        # Map over collection
        numbers = [100, 200, 300, 400, 500]
        map_results = executor.map(cpu_intensive_task, numbers)

        # Wait for results
        print("🚀 Executing tasks...")

        # Get individual results
        print(f"Result 1: {result1.get()}")
        print(f"Result 2: {result2.get()}")

        # Gather parallel results
        parallel_values = executor.gather(*parallel_results)
        print(f"Parallel results: {parallel_values}")

        # Gather map results
        map_values = executor.gather(*map_results)
        print(f"Map results: {map_values}")

        print("✅ All tasks completed!")
