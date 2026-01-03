"""Unified task decorator with full lifecycle support."""

import functools
import time
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from callpyback.executor import ExecutionMode, Executor
from callpyback.types import Message, SharedState, TaskContext

# Type aliases
Observer = Any  # Will be properly typed when observers are updated
ContextHandler = Callable[[TaskContext], None]


class TaskRunner:
    """Unified execution engine for tasks.

    Handles both direct calls and queue-triggered execution through
    the same code path, ensuring consistent observer and handler behavior.

    Example:
        runner = TaskRunner(
            func=my_func,
            topic="my.topic",
            executor=Executor(),
            on_execute=[TimingObserver()],
            on_success=lambda ctx: print(f"Done: {ctx.result}"),
        )

        result = runner.run("hello")  # Executes with full lifecycle
    """

    def __init__(
        self,
        func: Callable,
        topic: str,
        executor: Executor,
        queue: Optional[Any] = None,  # MessageQueue, avoid circular import
        on_execute: Optional[List[Observer]] = None,
        on_success: Optional[ContextHandler] = None,
        on_failure: Optional[ContextHandler] = None,
        on_complete: Optional[ContextHandler] = None,
        publish_result: bool = True,
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

    def run(self, *args, **kwargs) -> Any:
        """Execute task with full lifecycle.

        1. Create TaskContext
        2. Call on_execute observers (on_start)
        3. Execute function via executor
        4. Call on_success/on_failure observers
        5. Call on_complete handler
        6. Publish result to queue (optional)
        7. Return result (or raise exception)
        """
        # 1. Create context
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

        try:
            # 2. on_execute observers (on_start)
            for observer in self.on_execute:
                try:
                    observer.on_start(ctx)
                except Exception:
                    pass  # Don't let observer errors affect execution

            # 3. Execute via executor
            if self.executor.mode == ExecutionMode.SEQUENTIAL:
                ctx.result = self.func(*args, **kwargs)
            else:
                task_id = self.executor.submit(self.func, *args, **kwargs)
                task_result = self.executor.result(task_id)
                if task_result.is_failure:
                    raise Exception(task_result.error)
                ctx.result = task_result.value

            ctx.end_time = time.time()

            # 4. on_success: observers (on_end) + handler
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

            # 5. Publish success to queue
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
            # 6. on_complete always runs
            if self.on_complete:
                try:
                    self.on_complete(ctx)
                except Exception:
                    pass


def task(
    queue: Optional[Any] = None,
    topic: Optional[str] = None,
    executor: Optional[Executor] = None,
    on_execute: Optional[List[Observer]] = None,
    on_success: Optional[ContextHandler] = None,
    on_failure: Optional[ContextHandler] = None,
    on_complete: Optional[ContextHandler] = None,
    publish_result: bool = True,
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

    Example:
        from callpyback import task, MessageQueue, Executor, TimingObserver

        queue = MessageQueue()
        executor = Executor(mode=ExecutionMode.THREAD)
        timing = TimingObserver()

        @task(
            queue=queue,
            topic="process.data",
            executor=executor,
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

        return wrapper

    return decorator
