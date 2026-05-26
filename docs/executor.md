# LocalProcedureCaller

Unified local procedure caller with sequential, thread, and process modes.

`LocalProcedureCaller` is the **local request-reply** layer: you hand it a
callable and get a value back. Its remote counterpart is [RPC](rpc.md)
(`RPCClient.call` dispatches the same call/return to a worker process or
machine). Both satisfy the [`Caller` protocol](#the-caller-protocol), so the
[`@task`](task.md) decorator can target either via its `caller=` parameter.

> `Executor` is a **deprecated alias** for `LocalProcedureCaller` kept for
> back-compat (`Executor = LocalProcedureCaller`). Prefer
> `LocalProcedureCaller` in new code.

## Overview

`LocalProcedureCaller` provides:
- A single high-level entry point, `call(target, *args, **kwargs) -> value`
  (the `Caller` surface)
- Three execution modes: sequential, thread, process
- Lower-level task submission and result retrieval
- Map operations for batch processing
- Async/await support

`SEQUENTIAL` runs the callable inline at submit time; `THREAD` and
`PROCESS` submit to a pool and return a `task_id` you later resolve with
`result(task_id)`.

## The call() entry point

`call(target, *args, **kwargs)` returns the unwrapped value, hiding the
`submit` / `result` dance. In `SEQUENTIAL` mode it runs `target` directly;
in `THREAD` / `PROCESS` mode it submits and returns the resulting
`TaskResult.value`. This is the method that satisfies the `Caller` protocol.

```python
from eventforge import LocalProcedureCaller, ExecutionMode

def compute(n):
    return sum(range(n))

caller = LocalProcedureCaller(mode=ExecutionMode.THREAD, max_workers=4)
print(caller.call(compute, 1_000_000))   # 499999500000
```

## The Caller protocol

`Caller` is a `@runtime_checkable` `Protocol` with one method,
`call(target, *args, **kwargs) -> value`. `LocalProcedureCaller` (runs the
callable in-process) and [`RPCClient`](rpc.md) (dispatches to a remote method
by name) both satisfy it, so request-reply is one shape at two distances:

```
LocalProcedureCaller : RPCClient :: Local : Remote Procedure Call
```

```python
from eventforge import Caller, LocalProcedureCaller

caller = LocalProcedureCaller()
isinstance(caller, Caller)   # True (runtime-checkable)
```

Anything accepting a `Caller` -- notably [`@task(caller=...)`](task.md) --
can run the work locally or dispatch it remotely by swapping the `Caller`.

## Execution Modes

```python
from eventforge import LocalProcedureCaller, ExecutionMode

# Sequential (default) - runs in current thread
caller = LocalProcedureCaller(mode=ExecutionMode.SEQUENTIAL)

# Thread pool - for I/O-bound tasks
caller = LocalProcedureCaller(mode=ExecutionMode.THREAD, max_workers=4)

# Process pool - for CPU-bound tasks
caller = LocalProcedureCaller(mode=ExecutionMode.PROCESS, max_workers=4)
```

## Basic Usage

```python
from eventforge import LocalProcedureCaller, ExecutionMode

def compute(n):
    return sum(range(n))

with LocalProcedureCaller(mode=ExecutionMode.THREAD, max_workers=4) as caller:
    # Submit task
    task_id = caller.submit(compute, 1000000)

    # Get result
    result = caller.result(task_id)
    print(result.value)       # 499999500000
    print(result.status)      # TaskStatus.COMPLETED
    print(result.execution_time)
```

## Map Operations

Process multiple items in parallel:

```python
from eventforge import LocalProcedureCaller, ExecutionMode

def square(x):
    return x ** 2

with LocalProcedureCaller(mode=ExecutionMode.THREAD, max_workers=4) as caller:
    results = caller.map(square, [1, 2, 3, 4, 5])

    for r in results:
        print(r.value)  # 1, 4, 9, 16, 25
```

## Process Mode

For CPU-bound tasks, use process mode to bypass the GIL:

```python
from eventforge import LocalProcedureCaller, ExecutionMode

def cpu_intensive(n):
    """CPU-bound computation."""
    total = 0
    for i in range(n):
        total += i ** 2
    return total

# Functions must be picklable for process mode
with LocalProcedureCaller(mode=ExecutionMode.PROCESS, max_workers=4) as caller:
    results = caller.map(cpu_intensive, [100000, 200000, 300000])

    for r in results:
        print(f"Result: {r.value}, Time: {r.execution_time:.3f}s")
```

## Async Support

```python
import asyncio
from eventforge import LocalProcedureCaller, ExecutionMode

async def main():
    async with LocalProcedureCaller(mode=ExecutionMode.THREAD) as caller:
        # Async submit
        task_id = await caller.submit_async(lambda x: x ** 2, 10)

        # Async result
        result = await caller.result_async(task_id)
        print(result.value)  # 100

        # Async map
        results = await caller.map_async(lambda x: x * 2, [1, 2, 3])
        for r in results:
            print(r.value)

asyncio.run(main())
```

## Error Handling

Failed tasks return results with error information:

```python
from eventforge import LocalProcedureCaller

def failing_task(x):
    if x < 0:
        raise ValueError("Negative not allowed")
    return x * 2

with LocalProcedureCaller() as caller:
    task_id = caller.submit(failing_task, -5)
    result = caller.result(task_id)

    print(result.is_failure)   # True
    print(result.error)        # "Negative not allowed"
    print(result.error_type)   # "ValueError"
```

## Timeouts

```python
from eventforge import LocalProcedureCaller
import time

def slow_task():
    time.sleep(10)
    return "done"

with LocalProcedureCaller() as caller:
    task_id = caller.submit(slow_task)

    try:
        result = caller.result(task_id, timeout=2.0)
    except TimeoutError:
        print("Task timed out")
```

## API Reference

### Caller

```python
@runtime_checkable
class Caller(Protocol):
    """Structural protocol unifying local execution and remote dispatch.

    Both LocalProcedureCaller and RPCClient satisfy it.
    """
    def call(self, target: Callable | str, *args, **kwargs) -> Any: ...
```

### LocalProcedureCaller

```python
class LocalProcedureCaller:
    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
        max_workers: int = 4,
    ):
        """Create a caller with specified mode and worker count."""

    def call(self, target: Callable | str, *args, **kwargs) -> Any:
        """Run target and return its unwrapped value (the Caller surface).

        SEQUENTIAL mode runs target directly; THREAD / PROCESS submit and
        return the resulting TaskResult.value. Requires a callable target.
        """

    @property
    def mode(self) -> ExecutionMode:
        """Current execution mode."""
    
    def start(self) -> None:
        """Start the pool (called automatically on first submit)."""
    
    def stop(self, wait: bool = True) -> None:
        """Stop the pool."""
    
    def submit(
        self,
        func: Callable,
        *args,
        priority: int = 0,
        timeout: float = None,
        **kwargs,
    ) -> str:
        """Submit task. Returns task_id."""
    
    async def submit_async(self, func: Callable, *args, **kwargs) -> str:
        """Submit task asynchronously."""
    
    def result(self, task_id: str, timeout: float = None) -> TaskResult:
        """Get task result (blocking)."""
    
    async def result_async(self, task_id: str, timeout: float = None) -> TaskResult:
        """Get task result asynchronously."""
    
    def map(self, func: Callable, items: Iterable, timeout: float = None) -> List[TaskResult]:
        """Map function over items."""
    
    async def map_async(self, func: Callable, items: Iterable, timeout: float = None) -> List[TaskResult]:
        """Map function over items asynchronously."""


# Deprecated alias kept for back-compat:
Executor = LocalProcedureCaller
```

> Note: `submit` accepts a `priority` keyword for signature compatibility,
> but the current implementation does not prioritize the queue by it.

### ExecutionMode

```python
class ExecutionMode(str, Enum):
    SEQUENTIAL = "sequential"  # Run in current thread
    THREAD = "thread"          # Use thread pool
    PROCESS = "process"        # Use process pool
```

## Local vs Remote

`LocalProcedureCaller` is local request-reply. For the remote equivalent --
dispatching a call to a worker process or another machine and getting the
value back -- use [RPC](rpc.md): `RPCServer` registers methods and
`RPCClient.call(method, *args)` invokes them over a `MessageQueue`. Both
satisfy the [`Caller` protocol](#the-caller-protocol) and follow the same
call-and-return shape; the difference is distance.

To wire a `LocalProcedureCaller` into the `@task` facade (so a decorated
function runs through a thread/process pool with observers attached), pass it
as `@task(caller=...)`; pass an `RPCClient` instead to dispatch the same
function remotely -- see [Task Decorator](task.md). (`@task` also accepts a
deprecated `executor=` alias.)

### TaskResult

```python
class TaskResult(BaseModel):
    task_id: str
    status: TaskStatus        # PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    value: Any = None         # Return value on success
    error: str = None         # Error message on failure
    error_type: str = None    # Exception type name
    execution_time: float     # Execution duration in seconds
    worker_id: str            # Worker identifier
    
    @property
    def is_success(self) -> bool: ...
    
    @property
    def is_failure(self) -> bool: ...
```

## Examples

### Parallel File Processing

```python
from eventforge import LocalProcedureCaller, ExecutionMode
from pathlib import Path

def process_file(filepath):
    content = Path(filepath).read_text()
    word_count = len(content.split())
    return {"file": filepath, "words": word_count}

files = ["file1.txt", "file2.txt", "file3.txt"]

with LocalProcedureCaller(mode=ExecutionMode.THREAD, max_workers=4) as caller:
    results = caller.map(process_file, files)

    for r in results:
        if r.is_success:
            print(f"{r.value['file']}: {r.value['words']} words")
```

### CPU-Bound Batch Processing

```python
from eventforge import LocalProcedureCaller, ExecutionMode
import math

def calculate_primes(n):
    """Find primes up to n."""
    sieve = [True] * (n + 1)
    for i in range(2, int(math.sqrt(n)) + 1):
        if sieve[i]:
            for j in range(i*i, n + 1, i):
                sieve[j] = False
    return sum(1 for i in range(2, n + 1) if sieve[i])

ranges = [100000, 200000, 300000, 400000]

with LocalProcedureCaller(mode=ExecutionMode.PROCESS, max_workers=4) as caller:
    results = caller.map(calculate_primes, ranges)

    for r, n in zip(results, ranges):
        print(f"Primes up to {n}: {r.value}")
```

### Mixed Workload

```python
from eventforge import LocalProcedureCaller, ExecutionMode

# Use thread mode for I/O
io_caller = LocalProcedureCaller(mode=ExecutionMode.THREAD, max_workers=8)

# Use process mode for CPU
cpu_caller = LocalProcedureCaller(mode=ExecutionMode.PROCESS, max_workers=4)

def fetch_data(url):
    # I/O bound
    import urllib.request
    return urllib.request.urlopen(url).read()

def process_data(data):
    # CPU bound
    return len(data.split())

with io_caller, cpu_caller:
    # Fetch in parallel
    urls = ["http://example.com"] * 10
    fetch_results = io_caller.map(fetch_data, urls)

    # Process in parallel
    data_list = [r.value for r in fetch_results if r.is_success]
    process_results = cpu_caller.map(process_data, data_list)
```
