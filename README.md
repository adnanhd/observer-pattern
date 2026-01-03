# CallPyBack

Message-driven function pipelines with pub-sub, executors, and RPC.

## Installation

```bash
pip install callpyback

# Optional transports
pip install callpyback[redis]
pip install callpyback[zmq]
```

## Quick Start

### Pipeline

Chain functions with event-based flow control:

```python
from callpyback import Pipeline

def validate(data):
    if not data:
        raise ValueError("Empty data")
    return data

def transform(data):
    return data.upper()

def save(data):
    print(f"Saved: {data}")
    return data

result = (
    Pipeline()
    .pipe(validate)
    .pipe(transform)
    .pipe(save)
    .on_success(lambda r: print(f"Done: {r.value}"))
    .on_failure(lambda r: print(f"Error: {r.error}"))
    .run("hello")
)
# Output:
# Saved: HELLO
# Done: HELLO
```

### Task Decorator

Wrap functions with event handlers:

```python
from callpyback import task

@task(
    on_success=lambda r: print(f"Result: {r.value}"),
    on_failure=lambda r: print(f"Failed: {r.error}")
)
def compute(x, y):
    return x + y

result = compute(10, 20)
# Output: Result: 30
```

### Executor

Run tasks in sequential, thread, or process mode:

```python
from callpyback import Executor, ExecutionMode

def heavy_task(n):
    return sum(range(n))

# Thread-based execution
with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
    task_id = executor.submit(heavy_task, 1000000)
    result = executor.result(task_id)
    print(result.value)

# Process-based execution for CPU-bound tasks
with Executor(mode=ExecutionMode.PROCESS, max_workers=4) as executor:
    results = executor.map(heavy_task, [100000, 200000, 300000])
    for r in results:
        print(r.value)
```

### Message Queue

Pub-sub messaging with Pydantic validation:

```python
from callpyback import MessageQueue

queue = MessageQueue()

@queue.on("events.*")
def handle_event(message):
    print(f"Received: {message.topic} -> {message.payload}")

queue.publish("events.user", {"action": "login", "user": "alice"})
# Output: Received: events.user -> {'action': 'login', 'user': 'alice'}

# Request-reply pattern
@queue.on("math.add")
def add_handler(message):
    a, b = message.payload["a"], message.payload["b"]
    return a + b

result = queue.request("math.add", {"a": 10, "b": 20}, timeout=5.0)
print(result)  # 30
```

### RPC

Remote procedure calls over message queue:

```python
from callpyback import MessageQueue, Executor, RPCServer, RPCClient

queue = MessageQueue()
executor = Executor()

# Server
server = RPCServer(queue, executor, service_name="calculator")

@server.register()
def add(a: int, b: int) -> int:
    return a + b

@server.register()
def multiply(a: int, b: int) -> int:
    return a * b

server.start()

# Client
client = RPCClient(queue, service_name="calculator")
print(client.call("add", 10, 20))       # 30
print(client.multiply(5, 6))            # 30 (dynamic method access)

server.stop()
```

### Async Support

All components support async/await:

```python
import asyncio
from callpyback import MessageQueue, Executor, ExecutionMode

async def main():
    # Async message queue
    queue = MessageQueue()
    
    @queue.on("async.task")
    def handler(msg):
        return msg.payload * 2
    
    result = await queue.request_async("async.task", 21, timeout=5.0)
    print(result)  # 42
    
    # Async executor
    async with Executor(mode=ExecutionMode.THREAD) as executor:
        task_id = await executor.submit_async(lambda x: x ** 2, 10)
        result = await executor.result_async(task_id)
        print(result.value)  # 100

asyncio.run(main())
```

## API Reference

### Types

- `Message` - Pydantic model for queue messages
- `TaskRequest` - Task submission request
- `TaskResult` - Task execution result
- `TaskStatus` - Enum: PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
- `RPCRequest` / `RPCResponse` - RPC message types

### Transport

- `Transport` - Abstract base for message transports
- `MemoryTransport` - In-memory transport (default)

### MessageQueue

```python
queue = MessageQueue(transport=None)  # Uses MemoryTransport by default

queue.publish(topic, payload, **headers)  # Publish message
queue.subscribe(topic, handler)           # Subscribe to topic
queue.on(topic)                           # Decorator for subscription
queue.request(topic, payload, timeout)    # Request-reply (sync)
await queue.request_async(...)            # Request-reply (async)
```

### Executor

```python
executor = Executor(
    mode=ExecutionMode.SEQUENTIAL,  # SEQUENTIAL, THREAD, or PROCESS
    max_workers=4,
    queue=None  # Optional MessageQueue for events
)

task_id = executor.submit(func, *args, **kwargs)
result = executor.result(task_id, timeout=None)
results = executor.map(func, items)
executor.cancel(task_id)
stats = executor.stats()
```

### Pipeline

```python
pipeline = Pipeline(executor=None)

pipeline.pipe(func)           # Add step
pipeline.on_success(handler)  # Success handler
pipeline.on_failure(handler)  # Failure handler  
pipeline.on_complete(handler) # Completion handler (success or failure)
result = pipeline.run(input)  # Execute pipeline
```

### RPC

```python
# Server
server = RPCServer(queue, executor, service_name="myservice")
server.register(name=None)(func)  # Register method
server.start()
server.stop()

# Client
client = RPCClient(queue, service_name="myservice", timeout=30.0)
result = client.call(method, *args, **kwargs)
result = await client.call_async(method, *args, **kwargs)
result = client.method_name(*args)  # Dynamic access
```

## License

MIT
