# Observers

Profiling and monitoring for function execution.

## Overview

Observers provide hooks into function execution for:
- Timing and performance tracking
- Metrics collection (calls, success rate)
- Logging
- Memory and CPU profiling
- Custom profiling (GPU, FLOPs, etc.)

## Basic Usage

```python
from callpyback import observe, TimingObserver, MetricsObserver

timing = TimingObserver()
metrics = MetricsObserver()

@observe(timing, metrics)
def my_function(x):
    return x * 2

my_function(10)
my_function(20)

print(timing.stats)   # {'count': 2, 'avg': 0.0001, ...}
print(metrics.stats)  # {'calls': 2, 'successes': 2, ...}
```

## Built-in Observers

### TimingObserver

Tracks execution time with optional threshold alerts:

```python
from callpyback import observe, TimingObserver
import time

timing = TimingObserver(threshold=1.0)  # Alert if > 1 second

@observe(timing)
def slow_function():
    time.sleep(1.5)

slow_function()

print(timing.stats)
# {'count': 1, 'total': 1.5, 'avg': 1.5, 'min': 1.5, 'max': 1.5}

print(timing.timings)  # [1.5]
```

### MetricsObserver

Tracks call counts and success rates:

```python
from callpyback import observe, MetricsObserver

metrics = MetricsObserver()

@observe(metrics)
def maybe_fail(x):
    if x < 0:
        raise ValueError("Negative!")
    return x

maybe_fail(10)  # Success
maybe_fail(20)  # Success
try:
    maybe_fail(-1)  # Failure
except ValueError:
    pass

print(metrics.stats)
# {'calls': 3, 'successes': 2, 'failures': 1, 'success_rate': 0.666...}
```

### LoggingObserver

Structured logging with configurable verbosity:

```python
from callpyback import observe, LoggingObserver
import logging

logging.basicConfig(level=logging.INFO)

logger = LoggingObserver(
    log_args=True,    # Log function arguments
    log_result=True,  # Log return value
)

@observe(logger)
def add(a, b):
    return a + b

add(10, 20)
# INFO: Calling add with args=(10, 20), kwargs={}
# INFO: add completed in 0.0001s with result=30
```

### MemoryObserver

Tracks memory allocation using tracemalloc:

```python
from callpyback import observe, MemoryObserver

memory = MemoryObserver()

@observe(memory)
def allocate():
    return [i for i in range(100000)]

allocate()

print(memory.stats)
# {'count': 1, 'avg_current': 4000000, 'avg_peak': 4500000, 'max_peak': 4500000}
```

### CPUObserver

Tracks CPU time (user and system):

```python
from callpyback import observe, CPUObserver

cpu = CPUObserver()

@observe(cpu)
def compute():
    return sum(i ** 2 for i in range(100000))

compute()

print(cpu.stats)
# {'count': 1, 'total_user_time': 0.05, 'total_sys_time': 0.001, 'avg_cpu_percent': 98.5}
```

## Meter Class

Running average tracker for metrics:

```python
from callpyback import Meter

loss_meter = Meter("loss")
acc_meter = Meter("accuracy")

# Training loop
for batch in range(10):
    loss = 0.5 - batch * 0.04  # Simulated decreasing loss
    acc = 0.7 + batch * 0.03   # Simulated increasing accuracy
    
    loss_meter.update(loss)
    acc_meter.update(acc)

print(f"Loss: {loss_meter.avg:.4f}")  # Loss: 0.3200
print(f"Accuracy: {acc_meter.avg:.4f}")  # Accuracy: 0.8350

# Reset for next epoch
loss_meter.reset()
acc_meter.reset()
```

### MeterObserver

Combine meters with observer pattern:

```python
from callpyback import observe, MeterObserver

meter_obs = MeterObserver({
    "loss": lambda ctx: ctx.result.get("loss"),
    "accuracy": lambda ctx: ctx.result.get("accuracy"),
})

@observe(meter_obs)
def train_batch(batch_data):
    # Simulate training
    return {"loss": 0.5, "accuracy": 0.85}

for _ in range(10):
    train_batch(None)

print(meter_obs.summary())
# loss: avg=0.5000 (n=10) | accuracy: avg=0.8500 (n=10)
```

## Composite Observers

Combine multiple observers:

```python
from callpyback import observe, CompositeObserver, TimingObserver, MetricsObserver, LoggingObserver

composite = CompositeObserver([
    TimingObserver(),
    MetricsObserver(),
    LoggingObserver(),
])

@observe(composite)
def my_function():
    return 42
```

## Custom Observers

Create custom observers by subclassing `Observer`:

```python
from callpyback import Observer, ExecutionContext, observe

class GPUMemoryObserver(Observer):
    """Track GPU memory usage (requires torch)."""
    
    def __init__(self):
        self.measurements = []
    
    def on_start(self, ctx: ExecutionContext) -> None:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
                ctx.metadata["gpu_mem_start"] = torch.cuda.memory_allocated()
        except ImportError:
            pass
    
    def on_end(self, ctx: ExecutionContext) -> None:
        try:
            import torch
            if torch.cuda.is_available():
                peak = torch.cuda.max_memory_allocated()
                current = torch.cuda.memory_allocated()
                start = ctx.metadata.get("gpu_mem_start", 0)
                
                self.measurements.append({
                    "allocated": current - start,
                    "peak": peak,
                })
                
                ctx.metadata["gpu_mem_allocated"] = current - start
                ctx.metadata["gpu_mem_peak"] = peak
        except ImportError:
            pass

gpu = GPUMemoryObserver()

@observe(gpu)
def gpu_computation():
    import torch
    x = torch.randn(1000, 1000, device="cuda")
    return x @ x.T
```

### FLOPs Observer Example

```python
from callpyback import Observer, ExecutionContext, observe

class FLOPsObserver(Observer):
    """Estimate FLOPs for matrix operations."""
    
    def __init__(self):
        self.total_flops = 0
    
    def on_start(self, ctx: ExecutionContext) -> None:
        ctx.metadata["flops"] = 0
    
    def on_end(self, ctx: ExecutionContext) -> None:
        # Extract FLOPs from result metadata if available
        flops = ctx.metadata.get("flops", 0)
        self.total_flops += flops

flops_obs = FLOPsObserver()

@observe(flops_obs)
def matrix_multiply(a, b):
    # FLOPs for matrix multiply: 2 * M * N * K
    m, k = a.shape
    _, n = b.shape
    # Store FLOPs in result for observer to capture
    result = a @ b
    return result
```

## Callback Observer

Quick observer from callback functions:

```python
from callpyback import observe, CallbackObserver

observer = CallbackObserver(
    on_start=lambda ctx: print(f"Starting {ctx.func_name}"),
    on_end=lambda ctx: print(f"Finished in {ctx.execution_time:.4f}s"),
    on_error=lambda ctx: print(f"Error: {ctx.error}"),
)

@observe(observer)
def my_function():
    return 42
```

## ExecutionContext

Context passed to all observer methods:

```python
from dataclasses import dataclass
from typing import Any, Dict, Optional

@dataclass
class ExecutionContext:
    func_name: str              # Function name
    args: tuple                 # Positional arguments
    kwargs: Dict[str, Any]      # Keyword arguments
    start_time: float           # Start timestamp
    end_time: float             # End timestamp (after execution)
    result: Any                 # Return value (on success)
    error: Optional[Exception]  # Exception (on failure)
    metadata: Dict[str, Any]    # Custom metadata storage
    
    @property
    def execution_time(self) -> float:
        """Elapsed time in seconds."""
    
    @property
    def is_success(self) -> bool:
        """True if no error occurred."""
```

## API Reference

### observe decorator

```python
@observe(
    *observers: Observer,
    on_execute: Optional[Callable[[ExecutionContext], None]] = None,
)
def my_function():
    pass
```

### Observer (abstract base)

```python
class Observer(ABC):
    @abstractmethod
    def on_start(self, ctx: ExecutionContext) -> None:
        """Called before execution."""
    
    @abstractmethod
    def on_end(self, ctx: ExecutionContext) -> None:
        """Called after execution (success or failure)."""
    
    def on_error(self, ctx: ExecutionContext) -> None:
        """Called on error. Default: delegates to on_end."""
```

### TimingObserver

```python
class TimingObserver(Observer):
    def __init__(self, threshold: float = None, name: str = "timing"): ...
    
    @property
    def timings(self) -> List[float]: ...
    
    @property
    def stats(self) -> Dict[str, float]: ...
    
    def reset(self) -> None: ...
```

### MetricsObserver

```python
class MetricsObserver(Observer):
    def __init__(self, name: str = "metrics"): ...
    
    @property
    def stats(self) -> Dict[str, Union[int, float]]: ...
    
    def reset(self) -> None: ...
```

### Meter

```python
class Meter:
    def __init__(self, name: str = "meter"): ...
    
    def update(self, val: float, n: int = 1) -> None: ...
    
    def reset(self) -> None: ...
    
    @property
    def val(self) -> float: ...   # Last value
    @property
    def avg(self) -> float: ...   # Running average
    @property
    def sum(self) -> float: ...   # Total sum
    @property
    def count(self) -> int: ...   # Number of updates
```

## Examples

### Training Loop Profiling

```python
from callpyback import observe, TimingObserver, Meter, MeterObserver

# Create observers
forward_timer = TimingObserver(name="forward")
backward_timer = TimingObserver(name="backward")
loss_meter = Meter("loss")
acc_meter = Meter("accuracy")

@observe(forward_timer)
def forward_pass(model, x):
    return model(x)

@observe(backward_timer)
def backward_pass(loss):
    loss.backward()

# Training loop
for epoch in range(10):
    loss_meter.reset()
    acc_meter.reset()
    
    for batch in dataloader:
        output = forward_pass(model, batch)
        loss = criterion(output, target)
        
        backward_pass(loss)
        optimizer.step()
        
        loss_meter.update(loss.item())
        acc_meter.update(accuracy(output, target))
    
    print(f"Epoch {epoch}: loss={loss_meter.avg:.4f}, acc={acc_meter.avg:.4f}")
    print(f"  Forward: {forward_timer.stats['avg']*1000:.2f}ms")
    print(f"  Backward: {backward_timer.stats['avg']*1000:.2f}ms")
```

### API Endpoint Monitoring

```python
from callpyback import observe, TimingObserver, MetricsObserver, LoggingObserver

timing = TimingObserver(threshold=0.5)  # Alert if > 500ms
metrics = MetricsObserver()
logger = LoggingObserver()

@observe(timing, metrics, logger)
def api_handler(request):
    # Handle request
    return {"status": "ok"}

# After some requests
print(f"Total calls: {metrics.stats['calls']}")
print(f"Success rate: {metrics.stats['success_rate']:.1%}")
print(f"Avg response time: {timing.stats['avg']*1000:.2f}ms")
print(f"Slow requests: {sum(1 for t in timing.timings if t > 0.5)}")
```
