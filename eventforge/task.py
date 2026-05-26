"""Task decorator + TaskRunner -- callable that is also an Observable."""

import functools
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol, cast
from uuid import uuid4

from eventforge.caller import Caller
from eventforge.executor import LocalProcedureCaller
from eventforge.observers import Eventful, Meter, Observable
from eventforge.types import Message, SharedState, TaskContext

logger = logging.getLogger(__name__)

# Type alias for plain callback handlers passed via decorator kwargs.
ContextHandler = Callable[[TaskContext], None]


class TaskCallable(Protocol):
    """The callable produced by the :func:`task` decorator.

    It behaves like the wrapped function (``__call__``) but also carries
    the :class:`TaskRunner` and its Observable surface, attached by the
    decorator so callers can do ``my_task.success.on(handler)`` or inspect
    ``my_task.pool.stats``.
    """

    _runner: "TaskRunner"
    _task: bool
    _topic: str
    _executor: Caller
    _caller: Caller
    state: SharedState
    pool: "TaskPool | None"
    start: Eventful
    success: Eventful
    failure: Eventful
    complete: Eventful
    on: Callable[..., Any]
    fire: Callable[..., Any]
    subscribe: Callable[..., Any]

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


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

    def acquire(self, blocking: bool = True, timeout: float | None = None) -> bool:
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
    def stats(self) -> dict[str, int]:
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

        def __init__(self, pool: "TaskPool", blocking: bool, timeout: float | None):
            self.pool = pool
            self.blocking = blocking
            self.timeout = timeout
            self.acquired = False

        def __enter__(self) -> bool:
            self.acquired = self.pool.acquire(self.blocking, self.timeout)
            return self.acquired

        def __exit__(self, *args: Any) -> None:
            if self.acquired:
                self.pool.release()

    def slot(
        self, blocking: bool = True, timeout: float | None = None
    ) -> _AcquireContext:
        """Context manager for acquiring a pool slot.

        Example:
            with pool.slot() as acquired:
                if acquired:
                    do_work()
        """
        return self._AcquireContext(self, blocking, timeout)


class TaskRunner(Observable):
    """Unified execution engine for tasks.

    Handles both direct calls and queue-triggered execution through
    the same code path, ensuring consistent observer and handler behavior.

    Args:
        func: The function to execute
        topic: Topic name for queue integration
        caller: Caller used to dispatch the function (local or RPC)
        queue: Optional MessageQueue for pub-sub
        on_execute: Observers with on_start/on_success/on_failure lifecycle methods
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
            caller=LocalProcedureCaller(),
            max_instances=3,
            on_execute=[TimingMeter()],
            on_success=lambda ctx: print(f"Done: {ctx.result}"),
        )

        result = runner.run("hello")
    """

    def __init__(
        self,
        func: Callable[..., Any],
        topic: str,
        caller: Caller | None = None,
        queue: Any | None = None,  # MessageQueue, avoid circular import
        on_execute: list[Any] | None = None,
        on_start: ContextHandler | None = None,
        on_success: ContextHandler | None = None,
        on_failure: ContextHandler | None = None,
        on_complete: ContextHandler | None = None,
        publish_result: bool = True,
        max_instances: int | None = None,
        instance_timeout: float | None = None,
        executor: Caller | None = None,  # deprecated alias for ``caller``
    ):
        resolved = caller or executor
        if resolved is None:
            raise TypeError("TaskRunner requires a 'caller' (or 'executor')")
        self.func = func
        self.topic = topic
        self._caller = resolved
        # ``executor`` kept as a back-compat alias referencing the same caller.
        self.executor = resolved
        self.queue = queue
        self.publish_result = publish_result
        self.state = SharedState()

        # Lifecycle channels (Observable attributes).
        self.start: Eventful = Eventful()
        self.success: Eventful = Eventful()
        self.failure: Eventful = Eventful()
        self.complete: Eventful = Eventful()

        # Subscribe Meters / Observables that brought their own ``attach``.
        for obs in on_execute or []:
            if isinstance(obs, Meter):
                obs.attach(self)
            elif hasattr(obs, "attach"):
                obs.attach(self)
            else:
                # Plain Observer-style object with on_<event> methods:
                # wire each ``on_X`` method to the matching channel.
                for attr in dir(type(obs)):
                    if not attr.startswith("on_"):
                        continue
                    method = getattr(obs, attr, None)
                    if not callable(method):
                        continue
                    channel = getattr(self, attr[3:], None)
                    if isinstance(channel, Eventful):
                        channel.subscribe(method)

        # Subscribe decorator-kwarg callbacks to their channels.
        if on_start:
            self.start.subscribe(on_start)
        if on_success:
            self.success.subscribe(on_success)
        if on_failure:
            self.failure.subscribe(on_failure)
        if on_complete:
            self.complete.subscribe(on_complete)

        # Pool for concurrency limiting.
        self.max_instances = max_instances
        self.instance_timeout = instance_timeout
        self.pool = TaskPool(max_instances) if max_instances else None

    def run(self, *args: Any, **kwargs: Any) -> Any:
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

    def _execute(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        """Internal execution logic."""
        # 2. Create context. ``uuid4().hex`` is ~25% faster than ``str(uuid4())``
        # (skips the canonical 8-4-4-4-12 hyphenation pass) and still gives
        # the full 122 bits of entropy a UUIDv4 carries.
        ctx = TaskContext(
            task_id=uuid4().hex,
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

        logger.info(
            "task.start id=%s topic=%s func=%s",
            ctx.task_id,
            self.topic,
            self.func.__name__,
        )
        self.start.fire(ctx)

        try:
            # Uniform dispatch: a LocalProcedureCaller runs the body, while an
            # RPCClient dispatches to the remote method named ``func.__name__``
            # (the local body is the reference impl, not executed remotely).
            ctx.result = self._caller.call(self.func, *args, **kwargs)
        except Exception as e:
            ctx.error = e
            ctx.end_time = time.time()
            logger.warning(
                "task.failure id=%s topic=%s exc=%s elapsed=%.4fs: %s",
                ctx.task_id,
                self.topic,
                type(e).__name__,
                ctx.execution_time,
                e,
            )
            self.failure.fire(ctx)
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
        else:
            ctx.end_time = time.time()
            logger.info(
                "task.success id=%s topic=%s elapsed=%.4fs",
                ctx.task_id,
                self.topic,
                ctx.execution_time,
            )
            self.success.fire(ctx)
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
        finally:
            self.complete.fire(ctx)


def task(
    queue: Any | None = None,
    topic: str | None = None,
    caller: Caller | None = None,
    executor: Caller | None = None,
    on_execute: list[Any] | None = None,
    on_success: ContextHandler | None = None,
    on_failure: ContextHandler | None = None,
    on_complete: ContextHandler | None = None,
    publish_result: bool = True,
    max_instances: int | None = None,
    instance_timeout: float | None = None,
) -> Callable[[Callable[..., Any]], TaskCallable]:
    """Decorator that creates a callable task with full lifecycle support.

    The decorated function can be:
    - Called directly: result = my_task(args)
    - Triggered via queue: queue.publish(topic, args)

    Both paths use the same execution engine with full observer support.

    Args:
        queue: MessageQueue instance for pub-sub integration
        topic: Topic name for queue subscription (defaults to function name)
        caller: Caller used to dispatch the function -- a LocalProcedureCaller
            (default) runs it in-process, an RPCClient dispatches it to a
            remote worker by function name
        executor: Deprecated alias for ``caller`` (kept for back-compat)
        on_execute: List of observers to hook into execution lifecycle
        on_success: Handler called on successful execution (receives TaskContext)
        on_failure: Handler called on failed execution (receives TaskContext)
        on_complete: Handler called after execution, success or failure
        publish_result: If True, publishes to {topic}.success or {topic}.failure
        max_instances: Maximum concurrent executions (None = unlimited)
        instance_timeout: Timeout in seconds waiting for slot (None = forever)

    Example:
        from eventforge import task, MessageQueue, LocalProcedureCaller, TimingMeter

        queue = MessageQueue()
        caller = LocalProcedureCaller(mode=ExecutionMode.THREAD)
        timing = TimingMeter()

        @task(
            queue=queue,
            topic="process.data",
            caller=caller,
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

    def decorator(func: Callable[..., Any]) -> TaskCallable:
        # Resolve the caller once: explicit caller wins, then the deprecated
        # executor alias, else a default in-process LocalProcedureCaller.
        resolved: Caller = caller or executor or LocalProcedureCaller()
        _topic = topic or func.__name__

        # Create runner
        runner = TaskRunner(
            func=func,
            topic=_topic,
            caller=resolved,
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

            def queue_handler(message: Message) -> Any:
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

            queue.on(_topic, queue_handler)

        @functools.wraps(func)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            """Execute task with full lifecycle support."""
            return runner.run(*args, **kwargs)

        wrapper = cast(TaskCallable, _wrapper)

        # Attach metadata for introspection
        wrapper._runner = runner
        wrapper._task = True
        wrapper._topic = _topic
        wrapper._caller = resolved
        wrapper._executor = resolved  # deprecated alias; prefer ``_caller``

        # Expose state for external access
        wrapper.state = runner.state
        wrapper.pool = runner.pool

        # Expose runner's Observable surface on the wrapper so callers can
        # do ``my_task.success.on(handler)`` or ``my_task.on("failure", fn)``.
        wrapper.start = runner.start
        wrapper.success = runner.success
        wrapper.failure = runner.failure
        wrapper.complete = runner.complete
        wrapper.on = runner.on
        wrapper.fire = runner.fire
        wrapper.subscribe = runner.subscribe

        return wrapper

    return decorator
