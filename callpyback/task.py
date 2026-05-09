"""Unified task decorator with full lifecycle support."""

import functools
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from callpyback.executor import ExecutionMode, Executor
from callpyback.types import Message, SharedState, TaskContext

logger = logging.getLogger(__name__)

# Type aliases
ObserverType = Any  # Observer with on_start/on_end/on_error methods
ContextHandler = Callable[[TaskContext], None]  # Simple callback


class TaskPool:
    """Manages a pool of task instances with concurrency limiting.

    Provides semaphore-based concurrency control and tracking of
    active/queued tasks for load balancing.

    Example:
        pool = TaskPool(max_instances=3)

        with pool.acquire():
            # Only 3 concurrent executions allowed
            do_work()

        print(pool.stats)  # {'active': 0, 'max': 3, 'total_processed': 1}
    """

    def __init__(self, max_instances: int = 1):
        if max_instances < 1:
            raise ValueError("max_instances must be at least 1")

        self.max_instances = max_instances
        self._semaphore = threading.Semaphore(max_instances)
        self._active = 0
        self._total_processed = 0
        self._queued = 0
        self._lock = threading.Lock()

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """Acquire a slot in the pool.

        Args:
            blocking: If True, block until a slot is available
            timeout: Maximum time to wait (None = forever)

        Returns:
            True if slot acquired, False if timeout/non-blocking failed
        """
        with self._lock:
            self._queued += 1

        acquired = self._semaphore.acquire(blocking=blocking, timeout=timeout)

        with self._lock:
            self._queued -= 1
            if acquired:
                self._active += 1

        return acquired

    def release(self) -> None:
        """Release a slot back to the pool."""
        with self._lock:
            self._active -= 1
            self._total_processed += 1
        self._semaphore.release()

    @property
    def active(self) -> int:
        """Number of currently active instances."""
        with self._lock:
            return self._active

    @property
    def queued(self) -> int:
        """Number of tasks waiting for a slot."""
        with self._lock:
            return self._queued

    @property
    def available(self) -> int:
        """Number of available slots."""
        with self._lock:
            return self.max_instances - self._active

    @property
    def stats(self) -> Dict[str, int]:
        """Get pool statistics."""
        with self._lock:
            return {
                "active": self._active,
                "queued": self._queued,
                "available": self.max_instances - self._active,
                "max": self.max_instances,
                "total_processed": self._total_processed,
            }

    class _AcquireContext:
        """Context manager for pool slot acquisition."""

        def __init__(self, pool: "TaskPool", blocking: bool, timeout: Optional[float]):
            self.pool = pool
            self.blocking = blocking
            self.timeout = timeout
            self.acquired = False

        def __enter__(self) -> bool:
            self.acquired = self.pool.acquire(self.blocking, self.timeout)
            return self.acquired

        def __exit__(self, *args) -> None:
            if self.acquired:
                self.pool.release()

    def slot(
        self, blocking: bool = True, timeout: Optional[float] = None
    ) -> _AcquireContext:
        """Context manager for acquiring a pool slot.

        Example:
            with pool.slot() as acquired:
                if acquired:
                    do_work()
        """
        return self._AcquireContext(self, blocking, timeout)


class TaskRunner:
    """Unified execution engine for tasks.

    Handles both direct calls and queue-triggered execution through
    the same code path, ensuring consistent observer and handler behavior.

    Args:
        func: The function to execute
        topic: Topic name for queue integration
        executor: Executor for task execution
        queue: Optional MessageQueue for pub-sub
        on_execute: Observers with on_start/on_end/on_error lifecycle methods
        on_success: Callback called on success (receives TaskContext)
        on_failure: Callback called on failure (receives TaskContext)
        on_complete: Callback called after execution (always runs)
        publish_result: Auto-publish results to queue
        max_instances: Maximum concurrent executions (None = unlimited)
        instance_timeout: Timeout waiting for available slot (None = forever)

    Example:
        runner = TaskRunner(
            func=my_func,
            topic="my.topic",
            executor=Executor(),
            max_instances=3,
            on_execute=[TimingObserver()],
            on_success=lambda ctx: print(f"Done: {ctx.result}"),
        )

        result = runner.run("hello")
    """

    def __init__(
        self,
        func: Callable,
        topic: str,
        executor: Executor,
        queue: Optional[Any] = None,  # MessageQueue, avoid circular import
        on_execute: Optional[List[ObserverType]] = None,
        on_success: Optional[ContextHandler] = None,
        on_failure: Optional[ContextHandler] = None,
        on_complete: Optional[ContextHandler] = None,
        publish_result: bool = True,
        max_instances: Optional[int] = None,
        instance_timeout: Optional[float] = None,
    ):
        self.func = func
        self.topic = topic
        self.executor = executor
        self.queue = queue
        self.on_execute = on_execute or []
        self.on_success = on_success
        self.on_failure = on_failure
        self.on_complete = on_complete
        self.publish_result = publish_result
        self.state = SharedState()  # Shared across all invocations

        # Pool for concurrency limiting
        self.max_instances = max_instances
        self.instance_timeout = instance_timeout
        self.pool = TaskPool(max_instances) if max_instances else None

    def run(self, *args, **kwargs) -> Any:
        """Execute task with full lifecycle.

        1. Acquire pool slot (if max_instances set)
        2. Create TaskContext
        3. Call on_execute observers (on_start)
        4. Execute function via executor
        5. Call on_success/on_failure observers
        6. Call on_complete handler
        7. Publish result to queue (optional)
        8. Release pool slot
        9. Return result (or raise exception)
        """
        # 1. Acquire pool slot if concurrency limiting is enabled
        if self.pool:
            acquired = self.pool.acquire(blocking=True, timeout=self.instance_timeout)
            if not acquired:
                raise TimeoutError(
                    f"Timeout waiting for available slot in task pool "
                    f"(max_instances={self.max_instances})"
                )

        try:
            return self._execute(args, kwargs)
        finally:
            # Release pool slot
            if self.pool:
                self.pool.release()

    def _execute(self, args: tuple, kwargs: dict) -> Any:
        """Internal execution logic."""
        # 2. Create context
        ctx = TaskContext(
            task_id=str(uuid4()),
            func_name=self.func.__name__,
            topic=self.topic,
            args=args,
            kwargs=kwargs,
            executor=self.executor,
            start_time=time.time(),
            state=self.state,
        )

        # Add pool stats to metadata if available
        if self.pool:
            ctx.metadata["pool_stats"] = self.pool.stats

        try:
            logger.info("task.start id=%s topic=%s func=%s", ctx.task_id, self.topic, self.func.__name__)

            # 3. on_execute observers (on_start)
            for observer in self.on_execute:
                try:
                    observer.on_start(ctx)
                except Exception:
                    pass  # Don't let observer errors affect execution

            # 4. Execute via executor
            if self.executor.mode == ExecutionMode.SEQUENTIAL:
                ctx.result = self.func(*args, **kwargs)
            else:
                task_id = self.executor.submit(self.func, *args, **kwargs)
                task_result = self.executor.result(task_id)
                if task_result.is_failure:
                    raise Exception(task_result.error)
                ctx.result = task_result.value

            ctx.end_time = time.time()
            logger.info(
                "task.done id=%s topic=%s elapsed=%.4fs",
                ctx.task_id, self.topic, ctx.execution_time,
            )

            # 5. on_success: observers (on_end) + handler
            for observer in self.on_execute:
                try:
                    observer.on_end(ctx)
                except Exception:
                    pass

            if self.on_success:
                try:
                    self.on_success(ctx)
                except Exception:
                    pass

            # 6. Publish success to queue
            if self.publish_result and self.queue:
                try:
                    self.queue.publish(
                        f"{self.topic}.success",
                        {
                            "task_id": ctx.task_id,
                            "result": ctx.result,
                            "execution_time": ctx.execution_time,
                        },
                    )
                except Exception:
                    pass

            return ctx.result

        except Exception as e:
            ctx.error = e
            ctx.end_time = time.time()
            logger.warning(
                "task.error id=%s topic=%s exc=%s elapsed=%.4fs: %s",
                ctx.task_id, self.topic, type(e).__name__, ctx.execution_time, e,
            )

            # on_failure: observers (on_error) + handler
            for observer in self.on_execute:
                try:
                    observer.on_error(ctx)
                except Exception:
                    pass

            if self.on_failure:
                try:
                    self.on_failure(ctx)
                except Exception:
                    pass

            # Publish failure to queue
            if self.publish_result and self.queue:
                try:
                    self.queue.publish(
                        f"{self.topic}.failure",
                        {
                            "task_id": ctx.task_id,
                            "error": str(e),
                            "error_type": type(e).__name__,
                            "execution_time": ctx.execution_time,
                        },
                    )
                except Exception:
                    pass

            raise

        finally:
            # 7. on_complete always runs
            if self.on_complete:
                try:
                    self.on_complete(ctx)
                except Exception:
                    pass


def task(
    queue: Optional[Any] = None,
    topic: Optional[str] = None,
    executor: Optional[Executor] = None,
    on_execute: Optional[List[ObserverType]] = None,
    on_success: Optional[ContextHandler] = None,
    on_failure: Optional[ContextHandler] = None,
    on_complete: Optional[ContextHandler] = None,
    publish_result: bool = True,
    max_instances: Optional[int] = None,
    instance_timeout: Optional[float] = None,
):
    """Decorator that creates a callable task with full lifecycle support.

    The decorated function can be:
    - Called directly: result = my_task(args)
    - Triggered via queue: queue.publish(topic, args)

    Both paths use the same execution engine with full observer support.

    Args:
        queue: MessageQueue instance for pub-sub integration
        topic: Topic name for queue subscription (defaults to function name)
        executor: Executor instance for task execution (defaults to SEQUENTIAL)
        on_execute: List of observers to hook into execution lifecycle
        on_success: Handler called on successful execution (receives TaskContext)
        on_failure: Handler called on failed execution (receives TaskContext)
        on_complete: Handler called after execution, success or failure
        publish_result: If True, publishes to {topic}.success or {topic}.failure
        max_instances: Maximum concurrent executions (None = unlimited)
        instance_timeout: Timeout in seconds waiting for slot (None = forever)

    Example:
        from callpyback import task, MessageQueue, Executor, TimingObserver

        queue = MessageQueue()
        executor = Executor(mode=ExecutionMode.THREAD)
        timing = TimingObserver()

        @task(
            queue=queue,
            topic="process.data",
            executor=executor,
            max_instances=3,  # Only 3 concurrent executions
            on_execute=[timing],
            on_success=lambda ctx: print(f"Done: {ctx.result}"),
        )
        def process_data(data):
            return data.upper()

        # Direct call - full observer support
        result = process_data("hello")  # "HELLO"

        # Queue trigger - same execution path
        queue.publish("process.data", "world")

        # Both tracked by timing observer
        print(timing.stats)

        # Check pool stats
        print(process_data.pool.stats)
    """

    def decorator(func: Callable) -> Callable:
        # Use default executor if none provided
        _executor = executor or Executor()
        _topic = topic or func.__name__

        # Create runner
        runner = TaskRunner(
            func=func,
            topic=_topic,
            executor=_executor,
            queue=queue,
            on_execute=on_execute,
            on_success=on_success,
            on_failure=on_failure,
            on_complete=on_complete,
            publish_result=publish_result,
            max_instances=max_instances,
            instance_timeout=instance_timeout,
        )

        # Register queue subscription if queue provided
        if queue is not None:

            @queue.on(_topic)
            def queue_handler(message: Message):
                """Handle messages from queue by invoking the task."""
                payload = message.payload

                # Smart argument unpacking
                if isinstance(payload, dict):
                    # Dict payload -> kwargs
                    return runner.run(**payload)
                elif isinstance(payload, (list, tuple)):
                    # List/tuple payload -> args
                    return runner.run(*payload)
                else:
                    # Single value -> single arg
                    return runner.run(payload)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            """Execute task with full lifecycle support."""
            return runner.run(*args, **kwargs)

        # Attach metadata for introspection
        wrapper._runner = runner
        wrapper._task = True
        wrapper._topic = _topic
        wrapper._executor = _executor

        # Expose state for external access
        wrapper.state = runner.state

        # Expose pool for monitoring (if max_instances set)
        wrapper.pool = runner.pool

        return wrapper

    return decorator
