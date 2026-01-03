"""Profiling observers for task execution."""

import functools
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from callpyback.types import TaskResult, TaskStatus


@dataclass
class ExecutionContext:
    """Context passed to observers during execution."""

    func_name: str
    args: tuple
    kwargs: Dict[str, Any]
    start_time: float = 0.0
    end_time: float = 0.0
    result: Any = None
    error: Optional[Exception] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def execution_time(self) -> float:
        return self.end_time - self.start_time if self.end_time else 0.0

    @property
    def is_success(self) -> bool:
        return self.error is None


class Observer(ABC):
    """Base observer for execution profiling."""

    @abstractmethod
    def on_start(self, ctx: ExecutionContext) -> None:
        """Called before execution starts."""
        pass

    @abstractmethod
    def on_end(self, ctx: ExecutionContext) -> None:
        """Called after execution ends."""
        pass

    def on_error(self, ctx: ExecutionContext) -> None:
        """Called on execution error. Default delegates to on_end."""
        self.on_end(ctx)


class TimingObserver(Observer):
    """Tracks execution timing with threshold alerts."""

    def __init__(self, threshold: Optional[float] = None, name: str = "timing"):
        self.threshold = threshold
        self.name = name
        self._timings: List[float] = []
        self._lock = threading.Lock()

    def on_start(self, ctx: ExecutionContext) -> None:
        ctx.metadata[f"{self.name}_start"] = time.perf_counter()

    def on_end(self, ctx: ExecutionContext) -> None:
        start = ctx.metadata.get(f"{self.name}_start", ctx.start_time)
        elapsed = time.perf_counter() - start

        with self._lock:
            self._timings.append(elapsed)

        ctx.metadata[f"{self.name}_elapsed"] = elapsed

        if self.threshold and elapsed > self.threshold:
            ctx.metadata[f"{self.name}_exceeded"] = True

    @property
    def timings(self) -> List[float]:
        with self._lock:
            return self._timings.copy()

    @property
    def stats(self) -> Dict[str, float]:
        with self._lock:
            if not self._timings:
                return {"count": 0, "total": 0, "avg": 0, "min": 0, "max": 0}
            return {
                "count": len(self._timings),
                "total": sum(self._timings),
                "avg": sum(self._timings) / len(self._timings),
                "min": min(self._timings),
                "max": max(self._timings),
            }

    def reset(self) -> None:
        with self._lock:
            self._timings.clear()


class MetricsObserver(Observer):
    """Tracks execution metrics (calls, successes, failures)."""

    def __init__(self, name: str = "metrics"):
        self.name = name
        self._calls = 0
        self._successes = 0
        self._failures = 0
        self._lock = threading.Lock()

    def on_start(self, ctx: ExecutionContext) -> None:
        with self._lock:
            self._calls += 1

    def on_end(self, ctx: ExecutionContext) -> None:
        with self._lock:
            if ctx.is_success:
                self._successes += 1
            else:
                self._failures += 1

    @property
    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "calls": self._calls,
                "successes": self._successes,
                "failures": self._failures,
                "success_rate": self._successes / self._calls if self._calls else 0,
            }

    def reset(self) -> None:
        with self._lock:
            self._calls = 0
            self._successes = 0
            self._failures = 0


class MemoryObserver(Observer):
    """Tracks memory usage during execution."""

    def __init__(self, name: str = "memory"):
        self.name = name
        self._measurements: List[Dict[str, int]] = []
        self._lock = threading.Lock()

    def on_start(self, ctx: ExecutionContext) -> None:
        try:
            import tracemalloc

            tracemalloc.start()
            ctx.metadata[f"{self.name}_tracking"] = True
        except Exception:
            ctx.metadata[f"{self.name}_tracking"] = False

    def on_end(self, ctx: ExecutionContext) -> None:
        if not ctx.metadata.get(f"{self.name}_tracking"):
            return

        try:
            import tracemalloc

            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            measurement = {"current": current, "peak": peak}
            ctx.metadata[f"{self.name}_current"] = current
            ctx.metadata[f"{self.name}_peak"] = peak

            with self._lock:
                self._measurements.append(measurement)
        except Exception:
            pass

    @property
    def measurements(self) -> List[Dict[str, int]]:
        with self._lock:
            return self._measurements.copy()

    @property
    def stats(self) -> Dict[str, int]:
        with self._lock:
            if not self._measurements:
                return {"count": 0, "avg_current": 0, "avg_peak": 0, "max_peak": 0}
            return {
                "count": len(self._measurements),
                "avg_current": sum(m["current"] for m in self._measurements)
                // len(self._measurements),
                "avg_peak": sum(m["peak"] for m in self._measurements)
                // len(self._measurements),
                "max_peak": max(m["peak"] for m in self._measurements),
            }

    def reset(self) -> None:
        with self._lock:
            self._measurements.clear()


class FLOPsObserver(Observer):
    """Estimates floating point operations (requires function cooperation)."""

    def __init__(self, name: str = "flops"):
        self.name = name
        self._operations: List[int] = []
        self._lock = threading.Lock()

    def on_start(self, ctx: ExecutionContext) -> None:
        ctx.metadata[f"{self.name}_count"] = 0

    def on_end(self, ctx: ExecutionContext) -> None:
        flops = ctx.metadata.get(f"{self.name}_count", 0)
        elapsed = ctx.execution_time

        if elapsed > 0 and flops > 0:
            ctx.metadata[f"{self.name}_per_second"] = flops / elapsed

        with self._lock:
            self._operations.append(flops)

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            if not self._operations:
                return {"count": 0, "total": 0, "avg": 0}
            return {
                "count": len(self._operations),
                "total": sum(self._operations),
                "avg": sum(self._operations) / len(self._operations),
            }

    def reset(self) -> None:
        with self._lock:
            self._operations.clear()


class CompositeObserver(Observer):
    """Combines multiple observers."""

    def __init__(self, observers: List[Observer]):
        self.observers = observers

    def on_start(self, ctx: ExecutionContext) -> None:
        for obs in self.observers:
            try:
                obs.on_start(ctx)
            except Exception:
                pass

    def on_end(self, ctx: ExecutionContext) -> None:
        for obs in self.observers:
            try:
                obs.on_end(ctx)
            except Exception:
                pass

    def on_error(self, ctx: ExecutionContext) -> None:
        for obs in self.observers:
            try:
                obs.on_error(ctx)
            except Exception:
                pass


class CallbackObserver(Observer):
    """Observer using callback functions."""

    def __init__(
        self,
        on_start: Optional[Callable[[ExecutionContext], None]] = None,
        on_end: Optional[Callable[[ExecutionContext], None]] = None,
        on_error: Optional[Callable[[ExecutionContext], None]] = None,
    ):
        self._on_start = on_start
        self._on_end = on_end
        self._on_error = on_error

    def on_start(self, ctx: ExecutionContext) -> None:
        if self._on_start:
            self._on_start(ctx)

    def on_end(self, ctx: ExecutionContext) -> None:
        if self._on_end:
            self._on_end(ctx)

    def on_error(self, ctx: ExecutionContext) -> None:
        if self._on_error:
            self._on_error(ctx)
        elif self._on_end:
            self._on_end(ctx)


def observe(
    *observers: Observer,
    on_execute: Optional[Callable[[ExecutionContext], None]] = None,
):
    """Decorator to add observers to a function.

    Args:
        observers: Observer instances to attach
        on_execute: Callback called before execution (like previous on_call)

    Example:
        timing = TimingObserver(threshold=1.0)
        metrics = MetricsObserver()

        @observe(timing, metrics)
        def my_function(x):
            return x * 2

        # Or with on_execute callback
        @observe(on_execute=lambda ctx: print(f"Calling {ctx.func_name}"))
        def my_function(x):
            return x * 2
    """

    def decorator(func: Callable) -> Callable:
        all_observers = list(observers)
        if on_execute:
            all_observers.append(CallbackObserver(on_start=on_execute))

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ctx = ExecutionContext(
                func_name=func.__name__,
                args=args,
                kwargs=kwargs,
                start_time=time.time(),
            )

            # Notify start
            for obs in all_observers:
                try:
                    obs.on_start(ctx)
                except Exception:
                    pass

            try:
                result = func(*args, **kwargs)
                ctx.result = result
                ctx.end_time = time.time()

                # Notify end
                for obs in all_observers:
                    try:
                        obs.on_end(ctx)
                    except Exception:
                        pass

                return result

            except Exception as e:
                ctx.error = e
                ctx.end_time = time.time()

                # Notify error
                for obs in all_observers:
                    try:
                        obs.on_error(ctx)
                    except Exception:
                        pass

                raise

        wrapper._observers = all_observers
        return wrapper

    return decorator
