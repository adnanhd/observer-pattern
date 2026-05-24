# Executor

Unified task executor with sequential, thread, and process modes.

## Overview

`Executor` provides:
- Three execution modes: sequential, thread, process
- Task submission and result retrieval
- Map operations for batch processing
- Async/await support

## Execution Modes

```python
from eventforge import Executor, ExecutionMode

# Sequential (default) - runs in current thread
executor = Executor(mode=ExecutionMode.SEQUENTIAL)

# Thread pool - for I/O-bound tasks
executor = Executor(mode=ExecutionMode.THREAD, max_workers=4)

# Process pool - for CPU-bound tasks
executor = Executor(mode=ExecutionMode.PROCESS, max_workers=4)
```

## Basic Usage

```python
from eventforge import Executor, ExecutionMode

def compute(n):
    return sum(range(n))

with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
    # Submit task
    task_id = executor.submit(compute, 1000000)
    
    # Get result
    result = executor.result(task_id)
    print(result.value)       # 499999500000
    print(result.status)      # TaskStatus.COMPLETED
    print(result.execution_time)
```

## Map Operations

Process multiple items in parallel:

```python
from eventforge import Executor, ExecutionMode

def square(x):
    return x ** 2

with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
    results = executor.map(square, [1, 2, 3, 4, 5])
    
    for r in results:
        print(r.value)  # 1, 4, 9, 16, 25
```

## Process Mode

For CPU-bound tasks, use process mode to bypass the GIL:

```python
from eventforge import Executor, ExecutionMode

def cpu_intensive(n):
    """CPU-bound computation."""
    total = 0
    for i in range(n):
        total += i ** 2
    return total

# Functions must be picklable for process mode
with Executor(mode=ExecutionMode.PROCESS, max_workers=4) as executor:
    results = executor.map(cpu_intensive, [100000, 200000, 300000])
    
    for r in results:
        print(f"Result: {r.value}, Time: {r.execution_time:.3f}s")
```

## Async Support

```python
import asyncio
from eventforge import Executor, ExecutionMode

async def main():
    async with Executor(mode=ExecutionMode.THREAD) as executor:
        # Async submit
        task_id = await executor.submit_async(lambda x: x ** 2, 10)
        
        # Async result
        result = await executor.result_async(task_id)
        print(result.value)  # 100
        
        # Async map
        results = await executor.map_async(lambda x: x * 2, [1, 2, 3])
        for r in results:
            print(r.value)

asyncio.run(main())
```

## Error Handling

Failed tasks return results with error information:

```python
from eventforge import Executor

def failing_task(x):
    if x < 0:
        raise ValueError("Negative not allowed")
    return x * 2

with Executor() as executor:
    task_id = executor.submit(failing_task, -5)
    result = executor.result(task_id)
    
    print(result.is_failure)   # True
    print(result.error)        # "Negative not allowed"
    print(result.error_type)   # "ValueError"
```

## Timeouts

```python
from eventforge import Executor
import time

def slow_task():
    time.sleep(10)
    return "done"

with Executor() as executor:
    task_id = executor.submit(slow_task)
    
    try:
        result = executor.result(task_id, timeout=2.0)
    except TimeoutError:
        print("Task timed out")
```

## API Reference

### Executor

```python
class Executor:
    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
        max_workers: int = 4,
    ):
        """Create executor with specified mode and worker count."""
    
    @property
    def mode(self) -> ExecutionMode:
        """Current execution mode."""
    
    def start(self) -> None:
        """Start executor pool (called automatically on first submit)."""
    
    def stop(self, wait: bool = True) -> None:
        """Stop executor pool."""
    
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
```

### ExecutionMode

```python
class ExecutionMode(str, Enum):
    SEQUENTIAL = "sequential"  # Run in current thread
    THREAD = "thread"          # Use thread pool
    PROCESS = "process"        # Use process pool
```

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
from eventforge import Executor, ExecutionMode
from pathlib import Path

def process_file(filepath):
    content = Path(filepath).read_text()
    word_count = len(content.split())
    return {"file": filepath, "words": word_count}

files = ["file1.txt", "file2.txt", "file3.txt"]

with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
    results = executor.map(process_file, files)
    
    for r in results:
        if r.is_success:
            print(f"{r.value['file']}: {r.value['words']} words")
```

### CPU-Bound Batch Processing

```python
from eventforge import Executor, ExecutionMode
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

with Executor(mode=ExecutionMode.PROCESS, max_workers=4) as executor:
    results = executor.map(calculate_primes, ranges)
    
    for r, n in zip(results, ranges):
        print(f"Primes up to {n}: {r.value}")
```

### Mixed Workload

```python
from eventforge import Executor, ExecutionMode

# Use thread mode for I/O
io_executor = Executor(mode=ExecutionMode.THREAD, max_workers=8)

# Use process mode for CPU
cpu_executor = Executor(mode=ExecutionMode.PROCESS, max_workers=4)

def fetch_data(url):
    # I/O bound
    import urllib.request
    return urllib.request.urlopen(url).read()

def process_data(data):
    # CPU bound
    return len(data.split())

with io_executor, cpu_executor:
    # Fetch in parallel
    urls = ["http://example.com"] * 10
    fetch_results = io_executor.map(fetch_data, urls)
    
    # Process in parallel
    data_list = [r.value for r in fetch_results if r.is_success]
    process_results = cpu_executor.map(process_data, data_list)
```
