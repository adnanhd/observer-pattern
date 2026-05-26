"""Unified executor with sequential, thread, and process modes."""

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from enum import Enum
from typing import Any
from uuid import uuid4

from eventforge.types import TaskResult, TaskStatus

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    """Execution mode for tasks."""

    SEQUENTIAL = "sequential"
    THREAD = "thread"
    PROCESS = "process"


def _run_with_timing(
    task_id: str,
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Worker entry: time the call and return a structured result.

    Submitted directly to ProcessPoolExecutor, which pickles ``func`` /
    ``args`` / ``kwargs`` internally (a Python fundamental for cross-process
    dispatch). The previous custom ``pickle.dumps`` / ``pickle.loads`` layer
    around this function was redundant -- removed.
    """
    start = time.time()
    try:
        result = func(*args, **kwargs)
        return {
            "task_id": task_id,
            "status": "completed",
            "value": result,
            "error": None,
            "execution_time": time.time() - start,
            "worker_id": f"process-{os.getpid()}",
        }
    except Exception as e:
        return {
            "task_id": task_id,
            "status": "failed",
            "value": None,
            "error": str(e),
            "error_type": type(e).__name__,
            "execution_time": time.time() - start,
            "worker_id": f"process-{os.getpid()}",
        }


class LocalProcedureCaller:
    """Unified task executor with multiple execution modes."""

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
        max_workers: int = 4,
    ):
        self._mode = mode
        self._max_workers = max_workers
        self._results: dict[str, TaskResult] = {}
        self._futures: dict[str, Future[TaskResult | dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._pool: ThreadPoolExecutor | ProcessPoolExecutor | None = None
        self._running = False

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    def start(self) -> None:
        """Start executor pool."""
        if self._running:
            return

        if self._mode == ExecutionMode.THREAD:
            self._pool = ThreadPoolExecutor(max_workers=self._max_workers)
        elif self._mode == ExecutionMode.PROCESS:
            self._pool = ProcessPoolExecutor(max_workers=self._max_workers)

        self._running = True
        logger.info(
            "executor.start mode=%s max_workers=%d", self._mode.value, self._max_workers
        )

    def stop(self, wait: bool = True) -> None:
        """Stop executor pool."""
        if not self._running:
            return

        if self._pool:
            self._pool.shutdown(wait=wait)
            self._pool = None

        self._running = False
        logger.info("executor.stop mode=%s", self._mode.value)

    def submit(
        self,
        func: Callable[..., Any],
        *args: Any,
        priority: int = 0,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> str:
        """Submit task for execution. Returns task_id."""
        task_id = str(uuid4())

        if self._mode == ExecutionMode.SEQUENTIAL:
            result = self._execute_sync(task_id, func, args, kwargs)
            with self._lock:
                self._results[task_id] = result
        else:
            if not self._running:
                self.start()

            assert self._pool is not None  # set by start() for non-sequential modes
            future: Future[TaskResult | dict[str, Any]]
            if self._mode == ExecutionMode.THREAD:
                future = self._pool.submit(
                    self._execute_sync, task_id, func, args, kwargs
                )
            else:
                # Process mode: ProcessPoolExecutor pickles func/args/kwargs
                # internally to ship them to the worker.
                future = self._pool.submit(
                    _run_with_timing, task_id, func, args, kwargs
                )

            with self._lock:
                self._futures[task_id] = future

            def _done(
                f: Future[TaskResult | dict[str, Any]], tid: str = task_id
            ) -> None:
                self._on_complete(tid, f)

            future.add_done_callback(_done)

        return task_id

    async def submit_async(
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> str:
        """Submit task asynchronously."""
        loop = asyncio.get_event_loop()

        def _submit() -> str:
            return self.submit(func, *args, **kwargs)

        return await loop.run_in_executor(None, _submit)

    def result(self, task_id: str, timeout: float | None = None) -> TaskResult:
        """Get task result (blocking)."""
        deadline = time.time() + timeout if timeout else None

        while True:
            with self._lock:
                if task_id in self._results:
                    return self._results[task_id]

                future = self._futures.get(task_id)

            if future:
                try:
                    remaining = deadline - time.time() if deadline else None
                    if remaining is not None and remaining <= 0:
                        raise TimeoutError(f"Task {task_id} timed out")

                    raw = future.result(timeout=remaining)

                    # Process mode returns dict
                    if isinstance(raw, dict):
                        return TaskResult(
                            task_id=raw["task_id"],
                            status=TaskStatus(raw["status"]),
                            value=raw.get("value"),
                            error=raw.get("error"),
                            error_type=raw.get("error_type"),
                            execution_time=raw.get("execution_time", 0),
                            worker_id=raw.get("worker_id", ""),
                        )
                    return raw
                except (TimeoutError, FuturesTimeoutError):
                    raise TimeoutError(f"Task {task_id} timed out")
                except Exception as e:
                    return TaskResult(
                        task_id=task_id,
                        status=TaskStatus.FAILED,
                        error=str(e),
                        error_type=type(e).__name__,
                    )

            if deadline and time.time() >= deadline:
                raise TimeoutError(f"Task {task_id} not found")

            time.sleep(0.01)

    async def result_async(
        self, task_id: str, timeout: float | None = None
    ) -> TaskResult:
        """Get task result asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.result(task_id, timeout))

    def map(
        self,
        func: Callable[..., Any],
        items: Iterable[Any],
        timeout: float | None = None,
    ) -> list[TaskResult]:
        """Map function over items."""
        task_ids = [self.submit(func, item) for item in items]
        return [self.result(tid, timeout) for tid in task_ids]

    async def map_async(
        self,
        func: Callable[..., Any],
        items: Iterable[Any],
        timeout: float | None = None,
    ) -> list[TaskResult]:
        """Map function over items asynchronously."""
        task_ids = [await self.submit_async(func, item) for item in items]
        return [await self.result_async(tid, timeout) for tid in task_ids]

    def _execute_sync(
        self,
        task_id: str,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> TaskResult:
        """Execute task synchronously."""
        start = time.time()
        worker_id = f"thread-{threading.current_thread().name}"

        try:
            value = func(*args, **kwargs)
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                value=value,
                execution_time=time.time() - start,
                worker_id=worker_id,
            )
        except Exception as e:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                error_type=type(e).__name__,
                execution_time=time.time() - start,
                worker_id=worker_id,
            )

    def _on_complete(
        self, task_id: str, future: Future[TaskResult | dict[str, Any]]
    ) -> None:
        """Handle task completion."""
        try:
            result = future.result()
            if isinstance(result, dict):
                result = TaskResult(
                    task_id=result["task_id"],
                    status=TaskStatus(result["status"]),
                    value=result.get("value"),
                    error=result.get("error"),
                    error_type=result.get("error_type"),
                    execution_time=result.get("execution_time", 0),
                    worker_id=result.get("worker_id", ""),
                )
        except Exception as e:
            result = TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                error_type=type(e).__name__,
            )

        with self._lock:
            self._results[task_id] = result
            self._futures.pop(task_id, None)

    def call(self, target: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute the callable ``target`` and return its unwrapped value.

        Satisfies the :class:`~eventforge.caller.Caller` protocol; ``@task``
        uses it to run the task body locally (inline / thread / process).
        """
        if not callable(target):
            raise TypeError("LocalProcedureCaller.call needs a callable")
        if self._mode == ExecutionMode.SEQUENTIAL:
            return target(*args, **kwargs)
        tid = self.submit(target, *args, **kwargs)
        return self.result(tid).value

    def __enter__(self) -> "LocalProcedureCaller":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()


Executor = LocalProcedureCaller  # deprecated alias; prefer LocalProcedureCaller
