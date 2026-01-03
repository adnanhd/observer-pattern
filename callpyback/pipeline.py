"""Event-based function pipeline with decorator support."""

import asyncio
import functools
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

from callpyback.executor import ExecutionMode, Executor
from callpyback.queue import MessageQueue
from callpyback.types import Message, TaskResult, TaskStatus

T = TypeVar("T")
Handler = Callable[[Any], Any]
ErrorHandler = Callable[[Exception, Any], Any]


@dataclass
class PipelineStep:
    """Single step in pipeline."""

    func: Callable
    name: str
    on_success: List[Handler] = field(default_factory=list)
    on_failure: List[ErrorHandler] = field(default_factory=list)
    on_complete: List[Handler] = field(default_factory=list)


class Pipeline:
    """Chain functions with event-based flow control."""

    def __init__(
        self,
        executor: Optional[Executor] = None,
        queue: Optional[MessageQueue] = None,
    ):
        self._executor = executor or Executor()
        self._queue = queue
        self._steps: List[PipelineStep] = []
        self._global_on_success: List[Handler] = []
        self._global_on_failure: List[ErrorHandler] = []
        self._global_on_complete: List[Handler] = []

    def pipe(self, func: Callable, name: Optional[str] = None) -> "Pipeline":
        """Add function to pipeline."""
        step = PipelineStep(
            func=func,
            name=name or getattr(func, "__name__", f"step_{len(self._steps)}"),
        )
        self._steps.append(step)
        return self

    def on_success(self, handler: Handler) -> "Pipeline":
        """Add global success handler."""
        self._global_on_success.append(handler)
        return self

    def on_failure(self, handler: ErrorHandler) -> "Pipeline":
        """Add global failure handler."""
        self._global_on_failure.append(handler)
        return self

    def on_complete(self, handler: Handler) -> "Pipeline":
        """Add global completion handler."""
        self._global_on_complete.append(handler)
        return self

    def run(self, initial_input: Any = None) -> TaskResult:
        """Execute pipeline synchronously."""
        current = initial_input
        start_time = __import__("time").time()

        for step in self._steps:
            try:
                if self._executor.mode == ExecutionMode.SEQUENTIAL:
                    current = step.func(current)
                else:
                    task_id = self._executor.submit(step.func, current)
                    result = self._executor.result(task_id)
                    if result.is_failure:
                        raise Exception(result.error)
                    current = result.value

                # Step success handlers
                for handler in step.on_success:
                    try:
                        handler(current)
                    except Exception:
                        pass

                # Publish to queue if available
                if self._queue:
                    self._queue.publish(f"pipeline.{step.name}.success", current)

            except Exception as e:
                # Step failure handlers
                for handler in step.on_failure:
                    try:
                        result = handler(e, current)
                        if result is not None:
                            current = result
                            break
                    except Exception:
                        pass
                else:
                    # No handler recovered, trigger global failure
                    for handler in self._global_on_failure:
                        try:
                            handler(e, current)
                        except Exception:
                            pass

                    if self._queue:
                        self._queue.publish(
                            f"pipeline.{step.name}.failure",
                            {"error": str(e), "input": current},
                        )

                    return TaskResult(
                        task_id="pipeline",
                        status=TaskStatus.FAILED,
                        error=str(e),
                        error_type=type(e).__name__,
                        execution_time=__import__("time").time() - start_time,
                    )

            finally:
                # Step complete handlers
                for handler in step.on_complete:
                    try:
                        handler(current)
                    except Exception:
                        pass

        # Global success handlers
        for handler in self._global_on_success:
            try:
                handler(current)
            except Exception:
                pass

        # Global complete handlers
        for handler in self._global_on_complete:
            try:
                handler(current)
            except Exception:
                pass

        if self._queue:
            self._queue.publish("pipeline.complete", current)

        return TaskResult(
            task_id="pipeline",
            status=TaskStatus.COMPLETED,
            value=current,
            execution_time=__import__("time").time() - start_time,
        )

    async def run_async(self, initial_input: Any = None) -> TaskResult:
        """Execute pipeline asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.run(initial_input))


def pipeline(*funcs: Callable, executor: Optional[Executor] = None) -> Callable:
    """Create pipeline from functions."""
    p = Pipeline(executor=executor)
    for func in funcs:
        p.pipe(func)
    return lambda x: p.run(x)


def task(
    executor: Optional[Executor] = None,
    mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
    on_success: Optional[Handler] = None,
    on_failure: Optional[ErrorHandler] = None,
    on_complete: Optional[Handler] = None,
    queue: Optional[MessageQueue] = None,
    topic: Optional[str] = None,
):
    """Decorator to wrap function as a task with event handlers."""

    def decorator(func: Callable) -> Callable:
        _executor = executor or Executor(mode=mode)
        _topic = topic or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = __import__("time").time()

            try:
                if _executor.mode == ExecutionMode.SEQUENTIAL:
                    result = func(*args, **kwargs)
                else:
                    task_id = _executor.submit(func, *args, **kwargs)
                    task_result = _executor.result(task_id)
                    if task_result.is_failure:
                        raise Exception(task_result.error)
                    result = task_result.value

                # Success handler
                if on_success:
                    try:
                        on_success(result)
                    except Exception:
                        pass

                # Publish success
                if queue:
                    queue.publish(f"{_topic}.success", result)

                # Complete handler
                if on_complete:
                    try:
                        on_complete(result)
                    except Exception:
                        pass

                return result

            except Exception as e:
                # Failure handler
                if on_failure:
                    try:
                        recovery = on_failure(e, args)
                        if recovery is not None:
                            return recovery
                    except Exception:
                        pass

                # Publish failure
                if queue:
                    queue.publish(f"{_topic}.failure", {"error": str(e), "args": args})

                raise

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: wrapper(*args, **kwargs))

        wrapper.async_call = async_wrapper
        return wrapper

    return decorator
