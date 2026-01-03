# CallPyBack

Message-driven task execution with pub-sub, executors, and RPC.

## Installation

```bash
pip install callpyback

# Optional transports
pip install callpyback[redis]
pip install callpyback[zmq]
```

## Quick Start

### Task Decorator

The `@task` decorator is the core abstraction - callable-compatible with full lifecycle support:

```python
from callpyback import task, MessageQueue, Executor, ExecutionMode, TimingObserver

queue = MessageQueue()
executor = Executor(mode=ExecutionMode.THREAD)
timing = TimingObserver()

@task(
    queue=queue,
    topic="process.data",
    executor=executor,
    on_execute=[timing],  # Observers for profiling
    on_success=lambda ctx: print(f"Done: {ctx.result}"),
    on_failure=lambda ctx: print(f"Failed: {ctx.error}"),
)
def process_data(data):
    return data.upper()

# Direct call - full observer support, returns result
result = process_data("hello")  # "HELLO"

# Queue trigger - same execution path, same observers
queue.publish("process.data", "world")

# Both tracked by timing observer
print(timing.stats)  # {'count': 2, 'avg': 0.001, ...}
```

Key features:
- **Callable-compatible**: Direct calls return results, not wrapped objects
- **Unified execution**: Direct and queue-triggered use the same path
- **Observer hooks**: Profile with `TimingObserver`, `MetricsObserver`, etc.
- **Lifecycle handlers**: `on_success`, `on_failure`, `on_complete`
- **Auto-publish**: Results published to `{topic}.success` / `{topic}.failure`

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

@queue.on("events.user")
def handle_event(message):
    print(f"Received: {message.topic} -> {message.payload}")

queue.publish("events.user", {"action": "login", "user": "alice"})
# Output: Received: events.user -> {'action': 'login', 'user': 'alice'}

# Request-reply pattern
@queue.on("math.add")
def add_handler(message):
    a, b = message.payload["a"], message.payload["b"]
    queue.reply(message, a + b)

response = queue.request("math.add", {"a": 10, "b": 20}, timeout=5.0)
print(response.payload)  # 30
```

### Observers

Profile task execution with built-in observers:

```python
from callpyback import task, TimingObserver, MetricsObserver, observe

timing = TimingObserver(threshold=1.0)  # Alert if > 1s
metrics = MetricsObserver()

@task(on_execute=[timing, metrics])
def my_task(x):
    return x * 2

my_task(21)
my_task(42)

print(timing.stats)   # {'count': 2, 'avg': 0.001, 'min': ..., 'max': ...}
print(metrics.stats)  # {'calls': 2, 'successes': 2, 'failures': 0}

# Or use the @observe decorator for simpler cases
@observe(timing, metrics)
def simple_function(x):
    return x + 1
```

Available observers:
- `TimingObserver` - Execution timing with threshold alerts
- `MetricsObserver` - Call counts, success/failure rates
- `LoggingObserver` - Structured logging
- `MemoryObserver` - Memory usage tracking
- `CPUObserver` - CPU usage tracking
- `MeterObserver` - Running averages (for training loops)

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

### Remote Queue

Bridge message queues across nodes with remote subscriptions:

```python
from callpyback import MessageQueue, RemoteQueue

# Node 1
queue1 = MessageQueue()
remote1 = RemoteQueue(queue1, node_id="node-1")

# Node 2
queue2 = MessageQueue()
remote2 = RemoteQueue(queue2, node_id="node-2")

# Connect nodes
remote1.connect("node-2", queue2)
remote2.connect("node-1", queue1)

# Subscribe to remote topic
@remote1.subscribe_remote("node-2", "events.order")
def handle_order(msg):
    print(f"Node-1 received: {msg.payload}")

# Publish from node-2 to node-1
remote2.publish("events.order", {"id": 123, "status": "created"})
# Output: Node-1 received: {'id': 123, 'status': 'created'}

# Broadcast to all nodes
remote1.broadcast("events.system", {"action": "shutdown"})
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
    print(result.payload)  # 42
    
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
- `TaskContext` - Context passed through task lifecycle
- `SharedState` - Thread-safe state for observer data sharing
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
queue.register_task(topic, task_func)     # Register task for topic
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

### Task Decorator

```python
@task(
    queue=None,           # MessageQueue for pub-sub integration
    topic=None,           # Topic name (defaults to function name)
    executor=None,        # Executor instance (defaults to SEQUENTIAL)
    on_execute=None,      # List of observers for lifecycle hooks
    on_success=None,      # Handler called on success (receives TaskContext)
    on_failure=None,      # Handler called on failure (receives TaskContext)
    on_complete=None,     # Handler called after execution (success or failure)
    publish_result=True,  # Auto-publish to {topic}.success/{topic}.failure
)
def my_task(x):
    return x * 2

# Direct call
result = my_task(21)  # 42

# Access shared state
my_task.state.set("key", "value")
my_task.state.get("key")  # "value"
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

### RemoteQueue

```python
remote = RemoteQueue(queue, node_id="node-1")

remote.connect(remote_node_id, remote_queue)    # Connect to remote
remote.disconnect(remote_node_id)               # Disconnect
remote.subscribe_remote(node_id, topic)(handler)  # Subscribe decorator
remote.add_remote_subscription(node_id, topic, handler)  # Subscribe
remote.publish_remote(node_id, topic, payload)  # Publish to remote
remote.broadcast(topic, payload)                # Broadcast to all nodes
remote.close()                                  # Cleanup connections
```

## License

MIT
