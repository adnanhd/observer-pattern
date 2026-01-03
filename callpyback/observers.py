"""Profiling observers for task execution."""

import functools
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union


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
    """Base observer for execution profiling.

    Subclass this to create custom observers for GPU tracking,
    custom metrics, etc.

    Example:
        class GPUMemoryObserver(Observer):
            def on_start(self, ctx):
                ctx.metadata["gpu_mem_start"] = get_gpu_memory()

            def on_end(self, ctx):
                ctx.metadata["gpu_mem_used"] = (
                    get_gpu_memory() - ctx.metadata["gpu_mem_start"]
                )
    """

    @abstractmethod
    def on_start(self, ctx: ExecutionContext) -> None:
        """Called before execution starts."""
        pass

    @abstractmethod
    def on_end(self, ctx: ExecutionContext) -> None:
        """Called after execution ends (success or failure)."""
        pass

    def on_error(self, ctx: ExecutionContext) -> None:
        """Called on execution error. Default delegates to on_end."""
        self.on_end(ctx)


class TimingObserver(Observer):
    """Tracks execution timing with threshold alerts.

    Args:
        threshold: If set, marks executions exceeding this time (seconds)
        name: Prefix for metadata keys

    Example:
        timing = TimingObserver(threshold=1.0)

        @observe(timing)
        def slow_function():
            time.sleep(2)

        slow_function()
        print(timing.stats)  # {'count': 1, 'avg': 2.0, ...}
    """

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
    """Tracks execution metrics (calls, successes, failures).

    Example:
        metrics = MetricsObserver()

        @observe(metrics)
        def my_function():
            return 42

        my_function()
        print(metrics.stats)  # {'calls': 1, 'successes': 1, ...}
    """

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
    def stats(self) -> Dict[str, Union[int, float]]:
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


class LoggingObserver(Observer):
    """Structured logging observer.

    Args:
        logger: Logger instance or name
        level: Log level (default INFO)
        log_args: Whether to log function arguments
        log_result: Whether to log function result

    Example:
        @observe(LoggingObserver(log_args=True))
        def my_function(x, y):
            return x + y
    """

    def __init__(
        self,
        logger: Optional[Union[logging.Logger, str]] = None,
        level: int = logging.INFO,
        log_args: bool = False,
        log_result: bool = False,
        name: str = "logging",
    ):
        if logger is None:
            self.logger = logging.getLogger("callpyback")
        elif isinstance(logger, str):
            self.logger = logging.getLogger(logger)
        else:
            self.logger = logger

        self.level = level
        self.log_args = log_args
        self.log_result = log_result
        self.name = name

    def on_start(self, ctx: ExecutionContext) -> None:
        msg = f"Calling {ctx.func_name}"
        if self.log_args:
            msg += f" with args={ctx.args}, kwargs={ctx.kwargs}"
        self.logger.log(self.level, msg)

    def on_end(self, ctx: ExecutionContext) -> None:
        if ctx.is_success:
            msg = f"{ctx.func_name} completed in {ctx.execution_time:.4f}s"
            if self.log_result:
                msg += f" with result={ctx.result}"
            self.logger.log(self.level, msg)
        else:
            self.logger.error(
                f"{ctx.func_name} failed after {ctx.execution_time:.4f}s: {ctx.error}"
            )


class MemoryObserver(Observer):
    """Tracks memory usage during execution using tracemalloc.

    Example:
        memory = MemoryObserver()

        @observe(memory)
        def allocate_memory():
            return [i for i in range(1000000)]

        allocate_memory()
        print(memory.stats)  # {'count': 1, 'max_peak': ..., ...}
    """

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


class CPUObserver(Observer):
    """Tracks CPU usage during execution.

    Example:
        cpu = CPUObserver()

        @observe(cpu)
        def cpu_intensive():
            return sum(i**2 for i in range(1000000))

        cpu_intensive()
        print(cpu.stats)
    """

    def __init__(self, name: str = "cpu"):
        self.name = name
        self._measurements: List[Dict[str, float]] = []
        self._lock = threading.Lock()

    def on_start(self, ctx: ExecutionContext) -> None:
        try:
            import resource

            usage = resource.getrusage(resource.RUSAGE_SELF)
            ctx.metadata[f"{self.name}_user_start"] = usage.ru_utime
            ctx.metadata[f"{self.name}_sys_start"] = usage.ru_stime
        except Exception:
            pass

    def on_end(self, ctx: ExecutionContext) -> None:
        measurement = {}

        try:
            import resource

            usage = resource.getrusage(resource.RUSAGE_SELF)

            user_start = ctx.metadata.get(f"{self.name}_user_start", 0)
            sys_start = ctx.metadata.get(f"{self.name}_sys_start", 0)

            measurement["user_time"] = usage.ru_utime - user_start
            measurement["sys_time"] = usage.ru_stime - sys_start
            measurement["total_cpu_time"] = (
                measurement["user_time"] + measurement["sys_time"]
            )

            wall_time = ctx.execution_time
            if wall_time > 0:
                measurement["cpu_percent"] = (
                    measurement["total_cpu_time"] / wall_time
                ) * 100

            ctx.metadata[f"{self.name}_user_time"] = measurement["user_time"]
            ctx.metadata[f"{self.name}_sys_time"] = measurement["sys_time"]
            ctx.metadata[f"{self.name}_percent"] = measurement.get("cpu_percent", 0)
        except Exception:
            pass

        if measurement:
            with self._lock:
                self._measurements.append(measurement)

    @property
    def stats(self) -> Dict[str, float]:
        with self._lock:
            if not self._measurements:
                return {"count": 0}

            return {
                "count": len(self._measurements),
                "total_user_time": sum(
                    m.get("user_time", 0) for m in self._measurements
                ),
                "total_sys_time": sum(m.get("sys_time", 0) for m in self._measurements),
                "avg_cpu_percent": sum(
                    m.get("cpu_percent", 0) for m in self._measurements
                )
                / len(self._measurements),
            }

    def reset(self) -> None:
        with self._lock:
            self._measurements.clear()


class Meter:
    """Running average meter for tracking metrics.

    Example:
        loss_meter = Meter("loss")
        acc_meter = Meter("accuracy")

        for batch in dataloader:
            loss = train_step(batch)
            loss_meter.update(loss, n=batch_size)

        print(loss_meter.avg)
    """

    def __init__(self, name: str = "meter"):
        self.name = name
        self.reset()

    def reset(self) -> None:
        self.val = 0.0
        self.avg = 0.0
        self.sum = 0.0
        self.count = 0

    def update(self, val: float, n: int = 1) -> None:
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count if self.count > 0 else 0.0

    @property
    def stats(self) -> Dict[str, float]:
        return {
            "val": self.val,
            "avg": self.avg,
            "sum": self.sum,
            "count": self.count,
        }

    def __repr__(self) -> str:
        return f"Meter({self.name}: avg={self.avg:.4f}, count={self.count})"


class MeterObserver(Observer):
    """Observer that tracks running averages using Meter.

    Useful for training loops where you want to track loss, accuracy, etc.

    Args:
        meters: Dict mapping metric names to extract functions
        reset_on_start: Whether to reset meters on each execution

    Example:
        meter_obs = MeterObserver({
            "loss": lambda ctx: ctx.result.get("loss"),
            "accuracy": lambda ctx: ctx.result.get("accuracy"),
        })

        @observe(meter_obs)
        def train_batch(batch):
            return {"loss": 0.5, "accuracy": 0.9}
    """

    def __init__(
        self,
        meters: Optional[Dict[str, Callable[[ExecutionContext], float]]] = None,
        reset_on_start: bool = False,
        name: str = "meter",
    ):
        self.name = name
        self._meter_extractors = meters or {}
        self._meters: Dict[str, Meter] = {
            name: Meter(name) for name in self._meter_extractors
        }
        self._reset_on_start = reset_on_start
        self._lock = threading.Lock()

    def add_meter(
        self, name: str, extractor: Callable[[ExecutionContext], float]
    ) -> None:
        """Add a new meter."""
        with self._lock:
            self._meter_extractors[name] = extractor
            self._meters[name] = Meter(name)

    def on_start(self, ctx: ExecutionContext) -> None:
        if self._reset_on_start:
            self.reset()

    def on_end(self, ctx: ExecutionContext) -> None:
        if not ctx.is_success:
            return

        with self._lock:
            for name, extractor in self._meter_extractors.items():
                try:
                    value = extractor(ctx)
                    if value is not None:
                        self._meters[name].update(value)
                except Exception:
                    pass

    def get_meter(self, name: str) -> Optional[Meter]:
        return self._meters.get(name)

    @property
    def stats(self) -> Dict[str, Dict[str, float]]:
        with self._lock:
            return {name: meter.stats for name, meter in self._meters.items()}

    def reset(self) -> None:
        with self._lock:
            for meter in self._meters.values():
                meter.reset()

    def summary(self) -> str:
        lines = []
        with self._lock:
            for name, meter in self._meters.items():
                lines.append(f"{name}: avg={meter.avg:.4f} (n={meter.count})")
        return " | ".join(lines)


class CompositeObserver(Observer):
    """Combines multiple observers.

    Example:
        composite = CompositeObserver([
            TimingObserver(),
            MetricsObserver(),
            LoggingObserver(),
        ])

        @observe(composite)
        def my_function():
            return 42
    """

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
    """Observer using callback functions.

    Example:
        observer = CallbackObserver(
            on_start=lambda ctx: print(f"Starting {ctx.func_name}"),
            on_end=lambda ctx: print(f"Finished in {ctx.execution_time}s"),
        )
    """

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
        on_execute: Callback called before execution

    Example:
        @observe(
            TimingObserver(threshold=1.0),
            MetricsObserver(),
            LoggingObserver(),
        )
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
