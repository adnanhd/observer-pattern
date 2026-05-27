# Task Decorator

The `@task` decorator composes an [`Executor`](executor.md), an optional
[`MessageQueue`](queue.md), and [observers](observers.md) into a single
callable with full lifecycle support. It wires the existing pieces together
so you do not have to by hand.

`@task` runs the function body **locally**: the `executor=` parameter is an
[`Executor`](executor.md) (sequential by default) and decides *how* the body
runs in-process -- inline, in a thread pool, or in a process pool. For remote
execution you register a function on an [`RPCServer`](rpc.md) and call it by
name -- see
[Running Logic on a Remote Worker](#running-logic-on-a-remote-worker).

## Overview

```python
from eventforge import task, MessageQueue, TimingMeter

queue = MessageQueue()
timing = TimingMeter()

@task(
    queue=queue,
    topic="process.data",
    on_execute=[timing],
    on_success=lambda ctx: print(f"Done: {ctx.result}"),
)
def process_data(data):
    return data.upper()

# Direct call - returns result
result = process_data("hello")  # "HELLO"

# Queue trigger - same execution path
queue.publish("process.data", "world")
```

## Key Features

### Callable-Compatible

Unlike wrapper patterns that return special result objects, `@task` decorated functions return their actual result:

```python
@task()
def compute(x, y):
    return x + y

result = compute(10, 20)  # 30, not TaskResult(30)
```

### Unified Execution Path

Both direct calls and queue-triggered invocations use the same `TaskRunner`, ensuring consistent behavior:

```python
@task(queue=queue, topic="my.task", on_execute=[timing])
def my_task(x):
    return x * 2

# These use identical execution paths:
my_task(21)                      # Direct call
queue.publish("my.task", 21)     # Queue trigger
```

### Lifecycle Observers

Attach observers for profiling and monitoring:

```python
from eventforge import TimingMeter, MetricsMeter

timing = TimingMeter(threshold=1.0)
# MetricsMeter pulls a number from each result; reduction="sum" counts calls.
calls = MetricsMeter("calls", extract=lambda ctx: 1.0, reduction="sum")

@task(on_execute=[timing, calls])
def my_task(x):
    return x * 2

my_task(21)
print(timing.stats)   # {'value': 0.0001, 'count': 1.0}  -- value = mean elapsed
print(calls.stats)    # {'value': 1.0, 'count': 1.0}     -- value = sum of calls
```

### Lifecycle Handlers

React to task completion with handlers:

```python
@task(
    on_success=lambda ctx: print(f"Result: {ctx.result}"),
    on_failure=lambda ctx: print(f"Error: {ctx.error}"),
    on_complete=lambda ctx: print(f"Time: {ctx.execution_time}s"),
)
def my_task(x):
    return x * 2
```

Handlers receive a `TaskContext` with:
- `task_id` - Unique execution ID
- `func_name` - Function name
- `args`, `kwargs` - Call arguments
- `result` - Return value (on success)
- `error` - Exception (on failure)
- `execution_time` - Duration in seconds
- `state` - Shared state across invocations
- `metadata` - Observer-provided data

### Auto-Publishing

Tasks automatically publish results to queue topics:

```python
@task(queue=queue, topic="my.task", publish_result=True)
def my_task(x):
    return x * 2

# Success publishes to "my.task.success"
# Failure publishes to "my.task.failure"

@queue.on("my.task.success")
def on_success(msg):
    print(msg.payload)  # {"task_id": "...", "result": 42, "execution_time": 0.001}
```

Disable with `publish_result=False`.

## API Reference

```python
@task(
    queue=None,           # MessageQueue for pub-sub integration
    topic=None,           # Topic name (defaults to function name)
    executor=None,        # Executor (default) -- how the body runs
                          #   in-process (inline / thread / process)
    on_execute=None,      # list of observers (Meters, etc.)
    on_success=None,      # Callable[[TaskContext], None]
    on_failure=None,      # Callable[[TaskContext], None]
    on_complete=None,     # Callable[[TaskContext], None]
    publish_result=True,  # Auto-publish to {topic}.success/{topic}.failure
    max_instances=None,   # Concurrency cap (None = unlimited)
    instance_timeout=None,
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `queue` | `MessageQueue` | `None` | Queue for pub-sub. If provided with topic, subscribes automatically |
| `topic` | `str` | Function name | Topic for queue subscription and result publishing |
| `executor` | `Executor` | `Executor()` | Local execution backend: how the body runs in-process (inline / thread / process) |
| `on_execute` | `list` | `[]` | Observers (Meters, etc.) wired to the start / success / failure / complete lifecycle |
| `on_success` | `Callable` | `None` | Called on successful execution |
| `on_failure` | `Callable` | `None` | Called on failed execution |
| `on_complete` | `Callable` | `None` | Called after execution (success or failure) |
| `publish_result` | `bool` | `True` | Auto-publish results to queue |
| `max_instances` | `int` | `None` | Maximum concurrent executions (None = unlimited) |
| `instance_timeout` | `float` | `None` | Timeout waiting for a pool slot |

### Decorated Function Attributes

```python
@task(topic="my.task")
def my_func(x):
    return x

my_func._task       # True
my_func._topic      # "my.task"
my_func._executor   # the Executor
my_func._runner     # TaskRunner instance
my_func.state       # SharedState instance
```

## SharedState

Each task has a thread-safe `SharedState` for sharing data across invocations:

```python
@task()
def counter(increment):
    return counter.state.update("count", lambda x: (x or 0) + increment)

counter(1)  # 1
counter(5)  # 6
counter(3)  # 9

print(counter.state.get("count"))  # 9
```

### SharedState API

```python
state = SharedState()

state.set("key", value)           # Set value
state.get("key", default=None)    # Get value
state.update("key", func)         # Atomic update: func(old) -> new
state.delete("key")               # Delete key
state.clear()                     # Clear all
state.items()                     # Get copy of all data
"key" in state                    # Check existence
```

## TaskContext

Context passed to handlers and observers:

```python
@dataclass
class TaskContext:
    task_id: str                    # Unique execution ID
    func_name: str                  # Function name
    topic: Optional[str]            # Queue topic
    args: tuple                     # Positional arguments
    kwargs: Dict[str, Any]          # Keyword arguments
    executor: Optional[Executor]    # the resolved Executor
    start_time: float               # Start timestamp
    end_time: float                 # End timestamp
    result: Any                     # Return value
    error: Optional[Exception]      # Exception if failed
    state: Optional[SharedState]    # Shared state
    metadata: Dict[str, Any]        # Observer data

    @property
    def execution_time(self) -> float: ...
    
    @property
    def is_success(self) -> bool: ...
```

## Queue Integration

### Automatic Subscription

When `queue` and `topic` are provided, the task automatically subscribes:

```python
queue = MessageQueue()

@task(queue=queue, topic="process.data")
def process_data(data):
    return data.upper()

# This subscription is created automatically:
# @queue.on("process.data")
# def handler(msg): process_data(msg.payload)
```

### Payload Handling

Payloads are intelligently unpacked:

```python
@task(queue=queue, topic="my.task")
def my_task(a, b, c=None):
    return a + b + (c or 0)

# Dict -> kwargs
queue.publish("my.task", {"a": 1, "b": 2, "c": 3})  # my_task(a=1, b=2, c=3)

# List/tuple -> args
queue.publish("my.task", [1, 2, 3])  # my_task(1, 2, 3)

# Single value -> single arg
queue.publish("my.task", 42)  # my_task(42) - would fail here, needs 2 args
```

## Executor Integration (local execution modes)

Run tasks with different local execution modes by passing an `Executor` as
`executor=`:

```python
from eventforge import Executor, ExecutionMode

# Thread-based for I/O-bound tasks
thread_executor = Executor(mode=ExecutionMode.THREAD, max_workers=4)

@task(executor=thread_executor)
def fetch_url(url):
    # I/O-bound work
    pass

# Process-based for CPU-bound tasks
process_executor = Executor(mode=ExecutionMode.PROCESS, max_workers=4)

@task(executor=process_executor)
def compute_heavy(data):
    # CPU-bound work
    pass
```

## Running Logic on a Remote Worker

`@task` runs the body in-process. To run logic remotely, you define the
function **on the server** (where it actually runs) and call it **by name**
from a client with [RPC](rpc.md). The client needs no `@task` and no stub.

```python
from eventforge import task, MessageQueue, RPCServer, RPCClient, TimingMeter

# SERVER: define the function once, where it runs. @task gives it observability.
@task(on_execute=[TimingMeter()])
def predict(x):
    return x * 2

queue = MessageQueue()
server = RPCServer(queue, service_name="ml")
server.add_method("predict", predict)     # or: @server.register("predict")
server.serve(blocking=False)

# CLIENT: plain call, no @task, no stub -- runs predict ON the server.
client = RPCClient(queue, service_name="ml")
result = client.call("predict", 2)        # 4, with the server's observers firing
```

Because `predict` is a `@task`, its observers fire on the server around each
real execution. See the distributed worker pool in
[Remote Queue](remote.md) / `examples/07_distributed_workers.py`.

## Examples

### Chaining Tasks via Queue

```python
queue = MessageQueue()

@task(queue=queue, topic="step1")
def step1(x):
    return x * 2

@task(queue=queue, topic="step2")
def step2(x):
    return x + 10

@queue.on("step1.success")
def chain_to_step2(msg):
    step2(msg.payload["result"])

# Start chain
step1(5)  # -> step2(10) -> 20
```

### Error Handling

```python
@task(
    on_failure=lambda ctx: log_error(ctx.error),
    on_complete=lambda ctx: cleanup(),
)
def risky_task(data):
    if not data:
        raise ValueError("Empty data")
    return process(data)

try:
    risky_task(None)
except ValueError:
    pass  # on_failure already called
```

### Profiling with Observers

```python
from eventforge import TimingMeter, MetricsMeter, MemoryMeter

timing = TimingMeter(threshold=0.5)
metrics = MetricsMeter()
memory = MemoryMeter()

@task(on_execute=[timing, metrics, memory])
def analyzed_task(data):
    return process(data)

# Run many times
for item in large_dataset:
    analyzed_task(item)

# View statistics
print(f"Avg time: {timing.stats['value']:.3f}s")
print(f"Success rate: {metrics.stats['success_rate']:.1%}")
print(f"Peak memory: {memory.stats['max_peak'] / 1024 / 1024:.1f}MB")
```
