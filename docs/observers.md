# Observers

Profiling and monitoring for task execution.

## Overview

Observers provide hooks into task execution for:
- Timing and performance tracking
- Metrics collection (extracted from results)
- Logging
- Memory and CPU profiling
- Custom profiling (GPU, FLOPs, etc.)

The model is `Observable` + `Eventful` + `Dispatcher`:

- `Observable` -- container of named `Eventful` channels. Subscribe via
  `obj.success.on(fn)` or `obj.on("success", fn)`.
- `Eventful` -- one pub-sub channel. `.on(fn)` subscribes, `.fire(*args)`
  dispatches.
- `Meter` -- `Observable` subclass that measures one value per task call,
  accumulates observations and exposes one reduced `value` chosen by
  `reduction=` (default `"mean"`); `stats == {value, count}`. Emits a
  `measurement` event.
- `Reporter` -- `Observable` subclass that auto-subscribes its
  `@observe(MeterCls, "event")`-marked methods to upstream Meters.

A `@task(...)` decorated function is an `Observable` exposing four lifecycle
channels: `start`, `success`, `failure`, `complete`.

## Basic Usage

Attach meters to a task via `on_execute`:

```python
from eventforge import task, TimingMeter, MetricsMeter

timing = TimingMeter()
metrics = MetricsMeter("result", extract=lambda ctx: ctx.result)

@task(on_execute=[timing, metrics])
def my_function(x):
    return x * 2

my_function(10)
my_function(20)

print(timing.stats)   # {'value': <mean elapsed>, 'count': 2.0}
print(metrics.stats)  # {'value': 30.0, 'count': 2.0}  # mean of 20.0 and 40.0
```

`on_execute` accepts any number of meters; each is wired to the task's
lifecycle channels via `Meter.attach(task)`.

## Built-in Observers

All meters share the same `stats` shape: `{'value', 'count'}`, where `value`
is the single reduced metric chosen by `reduction=` (default `"mean"`; the
choices are `"mean"`, `"max"`, `"min"`, `"sum"`, `"last"`, `"count"`). An
unknown reduction name raises `ValueError`. Subclasses pass a sensible default
reduction (e.g. `MemoryMeter` defaults to `"max"`) that you can override.

### TimingMeter

Tracks per-call elapsed wall time, with an optional threshold flag:

```python
from eventforge import task, TimingMeter
import time

timing = TimingMeter(threshold=1.0)  # flags calls slower than 1 second

@task(on_execute=[timing])
def slow_function():
    time.sleep(1.5)

slow_function()

print(timing.stats)
# {'value': 1.5, 'count': 1.0}   # mean elapsed (default reduction="mean")
```

When a call exceeds `threshold`, `ctx.metadata["timing_exceeded"]` is set.

### MetricsMeter

Pulls a single numeric metric from `ctx.result` via an extractor callable:

```python
from eventforge import task, MetricsMeter

# Extract the "loss" field from the returned dict
loss = MetricsMeter("loss", extract=lambda ctx: ctx.result["loss"])

@task(on_execute=[loss])
def train_step(x):
    return {"loss": 0.5 - x * 0.01}

train_step(0)
train_step(1)

print(loss.stats)
# {'value': 0.495, 'count': 2.0}   # mean of 0.5 and 0.49 (default reduction="mean")
```

If the extractor raises or returns `None`, no measurement is recorded for
that call. Pass `reduction=` to change how the value is reduced, e.g.
`MetricsMeter("hits", extract=..., reduction="sum")` accumulates a running
total instead of a mean.

### LoggingReporter

`LoggingReporter` is a `Reporter`: instantiating one auto-subscribes it to
the `measurement` event of *every* `Meter` in the process via stdlib
logging. You do not pass it to `on_execute`; you just construct it.

```python
from eventforge import task, TimingMeter, LoggingReporter
import logging

logging.basicConfig(level=logging.INFO)

LoggingReporter(log_args=True, log_result=True)  # logs all Meter measurements

timing = TimingMeter()

@task(on_execute=[timing])
def add(a, b):
    return a + b

add(10, 20)
# INFO:eventforge:timing = 0.0001 args=(10, 20) kwargs={} result=30
```

### MemoryMeter

Tracks per-call memory delta via `tracemalloc`:

```python
from eventforge import task, MemoryMeter

memory = MemoryMeter()  # default reduction="max" -- value is the peak delta

@task(on_execute=[memory])
def allocate():
    return [i for i in range(100000)]

allocate()

print(memory.stats)
# {'value': 4000000.0, 'count': 1.0}   # peak memory delta (default reduction="max")
# ctx.metadata["memory_peak"] also holds the tracemalloc peak.
```

### CPUMeter

Tracks per-call user+system CPU time via `resource.getrusage`:

```python
from eventforge import task, CPUMeter

cpu = CPUMeter()

@task(on_execute=[cpu])
def compute():
    return sum(i ** 2 for i in range(100000))

compute()

print(cpu.stats)
# {'value': 0.05, 'count': 1.0}   # mean CPU time (default reduction="mean")
```

## Meter Aggregator

A bare `Meter` is an aggregator you drive manually with `update()`: it
accumulates observations and exposes one reduced `value` chosen by
`reduction=` (default `"mean"`). Useful for training-loop metrics independent
of tasks:

```python
from eventforge import Meter

loss_meter = Meter("loss")                  # default reduction="mean"
acc_meter = Meter("accuracy")
peak_meter = Meter("peak", reduction="max")  # override the default reduction

# Training loop
for batch in range(10):
    loss = 0.5 - batch * 0.04  # simulated decreasing loss
    acc = 0.7 + batch * 0.03   # simulated increasing accuracy

    loss_meter.update(loss)
    acc_meter.update(acc)
    peak_meter.update(acc)

print(f"Loss: {loss_meter.value:.4f}")          # mean loss
print(f"Accuracy: {acc_meter.value:.4f}")       # mean accuracy
print(f"Peak accuracy: {peak_meter.value:.4f}")  # max observed

# Reset for next epoch
loss_meter.reset()
acc_meter.reset()
```

`update(val, n=1)` accumulates the observation and fires the `update_event`
channel; `.value` returns the single reduced metric and `.stats` is
`{value, count}`. `reset()` clears state and fires `reset_event`. An unknown
`reduction=` name raises `ValueError`.

## Combining Multiple Observers

There is no composite-observer wrapper. To run several meters at once, pass
them as a list to `on_execute` -- each is attached to the task's lifecycle
channels:

```python
from eventforge import task, TimingMeter, MetricsMeter, MemoryMeter

@task(on_execute=[TimingMeter(), MemoryMeter(),
                  MetricsMeter("size", extract=lambda ctx: len(ctx.result))])
def my_function():
    return list(range(42))
```

Equivalently, attach meters to any `Observable` (or another `Meter`) by
hand with `meter.attach(source)`, or subscribe to channels directly:

```python
from eventforge import TimingMeter

timing = TimingMeter()

@task
def work():
    return 1

timing.attach(work)          # wires on_start/on_success/... to the channels
work.success.on(lambda ctx: print("done", ctx.result))  # plain callable too
work()
```

## Custom Observers

There is no `Observer` base class. Extend the system one of three ways.

### Custom Meter

Subclass `Meter` and override `measure(self, ctx) -> float | None` (and
optionally `on_start` to stash a baseline). The default `on_success` calls
`measure`, accumulates the observation, and fires `self.measurement`.
Construct as `MyMeter("name")` or `MyMeter("name", reduction="max")`:

```python
from eventforge import task, Meter
from eventforge.observers import Context

class GPUMemoryMeter(Meter):
    """Track GPU memory delta (requires torch)."""

    name = "gpu_mem"

    def on_start(self, ctx: Context) -> None:
        import torch
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
            ctx.metadata["gpu_mem_start"] = torch.cuda.memory_allocated()

    def measure(self, ctx: Context) -> float | None:
        import torch
        if not torch.cuda.is_available():
            return None
        start = ctx.metadata.get("gpu_mem_start", 0)
        ctx.metadata["gpu_mem_peak"] = torch.cuda.max_memory_allocated()
        return float(torch.cuda.memory_allocated() - start)

gpu = GPUMemoryMeter(reduction="max")  # value is the peak GPU memory delta

@task(on_execute=[gpu])
def gpu_computation():
    import torch
    x = torch.randn(1000, 1000, device="cuda")
    return x @ x.T

print(gpu.stats)  # {'value': <peak GPU memory delta>, 'count': N.0}
```

### Custom Reporter

Subclass `Reporter` and mark methods with `@observe(MeterCls, "event")`.
The marked methods auto-subscribe at `__init__` to the named event of every
instance of `MeterCls` (and its subclasses). Use this to ship measurements
somewhere -- a totals counter, a metrics backend, etc.:

```python
from eventforge import Reporter, Meter, TimingMeter, task, observe
from eventforge.observers import Context

class TotalsReporter(Reporter):
    """Sum every measurement emitted by any Meter."""

    def __init__(self) -> None:
        self.total = 0.0
        super().__init__()  # auto-wires the @observe method below

    @observe(Meter, "measurement")
    def _on_measurement(self, meter: Meter, value, ctx: Context) -> None:
        if value is not None:
            self.total += value

reporter = TotalsReporter()

@task(on_execute=[TimingMeter()])
def work():
    return 42

work()
work()
print(reporter.total)  # sum of the two timing measurements
```

The `measurement` event fires with `(meter, value, ctx)` -- match that
signature in the handler.

### Plain callable

For a quick hook, subscribe any function to a lifecycle channel via
`.on(...)`, or pass `on_start` / `on_success` / `on_failure` /
`on_complete` callbacks to `@task`:

```python
from eventforge import task

@task(
    on_start=lambda ctx: print(f"Starting {ctx.func_name}"),
    on_success=lambda ctx: print(f"Finished in {ctx.execution_time:.4f}s"),
    on_failure=lambda ctx: print(f"Error: {ctx.error}"),
)
def my_function():
    return 42

my_function()
```

## TaskContext / ExecutionContext

Lifecycle channels fire a context object. Tasks fire `TaskContext`; the
standalone meter machinery accepts the compatible `ExecutionContext`. Both
expose `func_name`, `args`, `kwargs`, `start_time`, `end_time`, `result`,
`error`, `metadata`, plus the `execution_time` and `is_success` properties:

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ExecutionContext:
    func_name: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    start_time: float = 0.0
    end_time: float = 0.0
    result: Any = None
    error: Exception | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def execution_time(self) -> float: ...   # end_time - start_time

    @property
    def is_success(self) -> bool: ...         # error is None
```

## API Reference

### task decorator

```python
@task(
    queue=None,
    topic=None,                # defaults to function name
    executor=None,             # Executor by default
    on_execute=None,           # list of Meters / objects with on_<event> methods
    on_success=None,           # Callable[[TaskContext], None]
    on_failure=None,
    on_complete=None,
    publish_result=True,
    max_instances=None,
    instance_timeout=None,
)
def my_function():
    ...
```

The decorated callable exposes `start` / `success` / `failure` / `complete`
Eventful channels (and `.on(...)` / `.fire(...)`), plus `.state` and
`.pool`.

### observe decorator

```python
def observe(target_cls: type, event: str):
    """Mark a Reporter method as a class-level subscriber to
    target_cls.<event>. Wired at the Reporter's __init__."""
```

### Meter

```python
class Meter(Observable):
    name: str = "meter"

    # reduction is a string validated against REDUCTIONS =
    # {"mean", "max", "min", "sum", "last", "count"}; unknown -> ValueError.
    def __init__(self, name=None, *, reduction: str = "mean", dispatcher=None): ...

    # aggregator
    def update(self, val: float, n: int = 1) -> None: ...
    def reset(self) -> None: ...

    @property
    def reduction(self) -> str: ...            # the reduction name

    @property
    def value(self) -> float: ...              # the single reduced metric

    @property
    def stats(self) -> dict[str, float]: ...   # {'value', 'count'}

    # lifecycle convention (override measure / on_start as needed)
    def measure(self, ctx) -> float | None: ...
    def on_start(self, ctx) -> None: ...
    def on_success(self, ctx) -> None: ...      # measure + update + emit
    def on_failure(self, ctx) -> None: ...
    def on_complete(self, ctx) -> None: ...

    def attach(self, source: Observable) -> "Meter": ...

    # Emission channels (Eventful):
    #   measurement   fires (meter, value, ctx) after each on_success
    #   update_event  fires (meter, val, n) after each update
    #   reset_event   fires (meter) after each reset
```

### TimingMeter

```python
class TimingMeter(Meter):
    def __init__(
        self,
        threshold: float | None = None,
        name: str = "timing",
        *,
        reduction: str = "mean",
    ): ...
```

### MetricsMeter

```python
class MetricsMeter(Meter):
    def __init__(
        self,
        name: str,
        extract: Callable[[Context], float | None],
        *,
        reduction: str = "mean",
    ): ...
```

### MemoryMeter

```python
class MemoryMeter(Meter):
    def __init__(self, name: str = "memory", *, reduction: str = "max"): ...
```

### CPUMeter

```python
class CPUMeter(Meter):
    def __init__(self, name: str = "cpu", *, reduction: str = "mean"): ...
```

### Reporter

```python
class Reporter(Observable):
    def __init__(self) -> None: ...   # auto-wires @observe-marked methods
```

## Examples

### Training Loop Profiling

```python
from eventforge import task, TimingMeter, Meter

forward_timer = TimingMeter(name="forward")
loss_meter = Meter("loss")
acc_meter = Meter("accuracy")

@task(on_execute=[forward_timer])
def forward_pass(model, x):
    return model(x)

# Training loop
for epoch in range(10):
    loss_meter.reset()
    acc_meter.reset()

    for batch in dataloader:
        output = forward_pass(model, batch)
        loss = criterion(output, target)
        loss.backward()
        optimizer.step()

        loss_meter.update(loss.item())
        acc_meter.update(accuracy(output, target))

    print(f"Epoch {epoch}: loss={loss_meter.value:.4f}, acc={acc_meter.value:.4f}")
    print(f"  Forward: {forward_timer.stats['value']*1000:.2f}ms")
```

### API Endpoint Monitoring

```python
from eventforge import task, TimingMeter, MetricsMeter, LoggingReporter

timing = TimingMeter(threshold=0.5)  # flag requests slower than 500ms
status = MetricsMeter("ok", extract=lambda ctx: 1.0)

LoggingReporter()  # logs every measurement

@task(on_execute=[timing, status])
def api_handler(request):
    return {"status": "ok"}

# After some requests
print(f"Total calls: {status.stats['count']}")
print(f"Avg response time: {timing.stats['value']*1000:.2f}ms")
```
