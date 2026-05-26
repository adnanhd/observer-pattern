# eventforge

[![Docker](https://img.shields.io/badge/Docker-deploy%2FDockerfile-2496ED?logo=docker&logoColor=white)](deploy/Dockerfile)
[![Apptainer](https://img.shields.io/badge/Apptainer-deploy%2Fapptainer-1D4ED8?logo=linuxcontainers&logoColor=white)](deploy/apptainer/eventforge.def)

Message-driven task execution with pub-sub, executors, and RPC.

`eventforge` is the **execution / dispatch** layer. Pair it with
[`registry-pattern`](https://github.com/adnanhd/registry-pattern) for the
**validation / serialization** layer:

- `registry-pattern` builds JSON-safe envelopes from your domain objects.
- `eventforge` ships them across threads, processes, or the network and
  runs the work on the other end.

The library is useful as a standalone in-process task runner too -- the
single-process path bypasses all transport overhead.

## Installation

```bash
pip install eventforge
```

Core install pulls only `pydantic` + `typing-extensions`. The TCP
transport is stdlib. Optional integrations (Pydantic Logfire, etc.)
have their own extras documented in `docs/`.

## When to use which queue

| You want... | Use |
|---|---|
| Local pub-sub in one process | `MessageQueue(transport=MemoryTransport())` |
| Competing-consumer work queue with ack/nack + DLQ | `WorkQueue` (extends MessageQueue) |
| Cross-process / cross-machine pub-sub or RPC | `MessageQueue(transport=TCPServerTransport(...))` and `TCPClientTransport(...)` on the client |
| RPC over an existing queue | `RPCServer(queue)` / `RPCClient(queue)` |

## Quick Start

### Task Decorator

The `@task` decorator is the core abstraction - callable-compatible with full lifecycle support:

```python
from eventforge import task, MessageQueue, Executor, ExecutionMode, TimingMeter

queue = MessageQueue()
executor = Executor(mode=ExecutionMode.THREAD)
timing = TimingMeter()

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
- **Observer hooks**: Profile with `TimingMeter`, `MetricsMeter`, etc.
- **Lifecycle handlers**: `on_success`, `on_failure`, `on_complete`
- **Auto-publish**: Results published to `{topic}.success` / `{topic}.failure`

#### Local vs remote dispatch

The same `@task` can run locally or dispatch to a remote RPC worker via the
`caller=` parameter. The local function body is the reference impl; when a
remote caller is used, the body is NOT executed -- instead the server's
registered method of the SAME name runs.

```python
from eventforge import task, MessageQueue, LocalProcedureCaller, RPCClient

# Local: LocalProcedureCaller runs the body in-process.
@task(caller=LocalProcedureCaller())
def predict(x):
    return x * 2

predict(5)  # 10, runs locally

# Remote: RPCClient dispatches to the worker's "predict" method by name.
client = RPCClient(MessageQueue(), service_name="ml")

@task(caller=client)
def predict(x):
    return x * 2  # reference impl only; the remote "predict" actually runs

predict(5)  # -> result computed by the remote RPC worker
```

### LocalProcedureCaller

Run tasks in sequential, thread, or process mode. (`Executor` remains as a
deprecated alias for `LocalProcedureCaller`; prefer the new name.)

```python
from eventforge import Executor, ExecutionMode

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
from eventforge import MessageQueue

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
from eventforge import task, TimingMeter, MetricsMeter, observe

timing = TimingMeter(threshold=1.0)  # Alert if > 1s
metrics = MetricsMeter()

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
- `TimingMeter` - Execution timing with threshold alerts
- `MetricsMeter` - Call counts, success/failure rates
- `LoggingReporter` - Structured logging
- `MemoryMeter` - Memory usage tracking
- `CPUMeter` - CPU usage tracking
- `Meter` - Running averages (for training loops)

### RPC

Remote procedure calls over message queue:

```python
from eventforge import MessageQueue, Executor, RPCServer, RPCClient

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

server.serve()

# Client
client = RPCClient(queue, service_name="calculator")
print(client.call("add", 10, 20))       # 30
print(client.multiply(5, 6))            # 30 (dynamic method access)

server.stop()  # serve() takes a stop_event for graceful shutdown
```

### Remote Queue

Bridge message queues across nodes with remote subscriptions:

```python
from eventforge import MessageQueue, RemoteQueue

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
from eventforge import MessageQueue, Executor, ExecutionMode

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

## Distributed execution: local builds, remote runs

The intended deployment for ML / data pipelines:

- **Local** process builds work envelopes (`registry-pattern.serialize`)
  and dispatches them via `RPCClient`.
- **Remote** workers run `RPCServer` on a TCP port, accept envelopes,
  reconstruct objects with `registry.build(...)`, run the work, return
  JSON-friendly results.
- eventforge owns the wire (JSON over TCP, no pickle); registry-pattern
  owns the schema (Pydantic validation on both ends).

See `examples/06_registry_integration.py` for the in-process version
and `examples/07_distributed_workers.py` for the cross-process variant
with N workers + round-robin client.

### Containerized topology (Docker / Apptainer)

The cross-process variant above containerizes into an
**eventforge-network**: a pool of RPC *server* nodes and one or more
*demander* (client) nodes that round-robin across them.

```
demander  --RPC (JSON/TCP)-->  server1
                          \-->  server2   (round-robin, client-side)
                          \-->  server3
```

Each server runs the generic worker entrypoint against a handler module
-- no transport boilerplate, no inlined worker source:

```bash
python -m eventforge.worker --import handlers --service math --port 9090
# handlers.py exposes:  HANDLERS = {"compute": compute};  SERVICE_NAME = "math"
```

Run the whole topology on one machine (3 servers + a demander):

```bash
docker compose -f deploy/docker-compose.yml up --build
```

**Scope, honestly:** this is an RPC compute-worker pool for a *trusted*
network -- request/response, client-side load balancing (the demander
needs every server address; no broker, no discovery), and the TCP
transport has no auth/TLS. It is **not** a durable job queue:
`WorkQueue`'s competing-consumer / ack-nack / DLQ machinery is
in-process only and does not cross containers. For brokered, durable
cross-machine queues use Celery / RQ / Dramatiq; eventforge's niche is
scaling code *already* on the eventforge + registry-pattern stack
without a second framework. Full guide and the `eventforge.worker`
contract: [`deploy/README.md`](deploy/README.md).

## Logging

Core lifecycle events emit stdlib `logging` at INFO -- no observer
needed for basic visibility:

```python
import logging
logging.basicConfig(level=logging.INFO)
# now @task calls emit task.start / task.done / task.error
```

`LoggingReporter` stays for the case where you want args/result detail
beyond the default.

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
- `TCPServerTransport(host, port)` / `TCPClientTransport(host, port)` --
  JSON-over-TCP across processes / machines

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

### LocalProcedureCaller (alias: Executor)

```python
executor = LocalProcedureCaller(
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
    caller=None,          # Caller: LocalProcedureCaller (default) or RPCClient
    executor=None,        # Deprecated alias for caller
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
server.serve()
server.stop()  # serve() takes a stop_event for graceful shutdown

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
