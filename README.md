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

## Concepts

The mental model is a 2x2. One axis is *what kind of exchange* you want;
the other is *where the other side lives*.

- **pub-sub** -- publish / subscribe, fire-and-forget. The sender does not
  get a return value; zero or more subscribers react.
- **request-reply** -- call / register, returns a value. One caller, one
  result.
- **local** -- same process.
- **remote** -- another process or machine, reached over a `Transport`.

|                  | local                  | remote        |
|------------------|------------------------|---------------|
| **pub-sub**      | `MessageQueue`         | `RemoteQueue` |
| **request-reply**| `LocalProcedureCaller` | RPC (`RPCServer` / `RPCClient`) |

The request-reply row is unified by one structural protocol, `Caller`:
`LocalProcedureCaller` runs a callable in-process, `RPCClient` dispatches it
to a remote worker by name, and both expose the same `.call(target, *args)`.
That is the analogy `LocalProcedureCaller : RPCClient :: Local : Remote
Procedure Call`.

The `Transport` (Memory or TCP) is *where* local-vs-remote actually lives:
the same `MessageQueue` API runs in-process on `MemoryTransport` or across
the network on a TCP transport. `@task` is **not** a fifth box -- it is a
facade that composes a `Caller` + a `MessageQueue` + `Observers` into one
decorated callable.

## Transport Layer

A `Transport` is the wire under a `MessageQueue`. Two ship in the box:

- `MemoryTransport` -- in-process, thread-safe, the default. Zero
  serialization, zero sockets.
- `TCPServerTransport(host, port)` / `TCPClientTransport(host, port)` --
  length-prefixed JSON over a TCP socket (`[4-byte big-endian length][JSON]`),
  for cross-process / cross-machine delivery. The server must be
  `.start()`ed; the client must be `.connect()`ed.

All transports implement one small ABC, so they are interchangeable under
`MessageQueue`, `RPCServer`, and `RPCClient`:

```python
class Transport(ABC):
    def send(self, message: Message) -> None: ...
    def receive(self, topic, timeout=None) -> Message | None: ...
    async def receive_async(self, topic, timeout=None) -> Message | None: ...
    def subscribe(self, topic, callback) -> str: ...
    def unsubscribe(self, subscription_id) -> bool: ...
    def close(self) -> None: ...
```

Swapping transports is a constructor change; nothing above the transport
moves:

```python
from eventforge import MessageQueue
from eventforge.transports.tcp import TCPServerTransport

# in-process (default)
local = MessageQueue()

# cross-process: same MessageQueue API, different wire
transport = TCPServerTransport(host="127.0.0.1", port=9090)
transport.start()
networked = MessageQueue(transport=transport)
```

Because the ABC is this small, you could add a Redis or NATS transport by
implementing those six methods -- nothing else in the stack needs to know.

## Messaging

Pub-sub: fire-and-forget, no return value.

### MessageQueue (local, one channel)

`MessageQueue` is topic-keyed pub-sub over a single transport. Subscribe
with the `@queue.on(...)` decorator (or `subscribe`), publish with
`publish`. It also supports a request-reply helper (`request` / `reply`)
on top of the same channel.

```python
from eventforge import MessageQueue

queue = MessageQueue()

@queue.on("events.user")
def handle_event(message):
    print(f"Received: {message.topic} -> {message.payload}")

queue.publish("events.user", {"action": "login", "user": "alice"})
# Received: events.user -> {'action': 'login', 'user': 'alice'}

# Request-reply over the same queue
@queue.on("math.add")
def add_handler(message):
    a, b = message.payload["a"], message.payload["b"]
    queue.reply(message, a + b)

response = queue.request("math.add", {"a": 10, "b": 20}, timeout=5.0)
print(response.payload)  # 30
```

Topic strings support `*` (one segment) and `**` (any number of segments)
patterns. The same queue works across processes by swapping in a TCP
transport (see [Transport Layer](#transport-layer)).

### RemoteQueue (push-only switchboard across nodes)

`RemoteQueue` is a node-addressing layer over `MessageQueue`. It owns one
outbound TCP link per peer and routes `send` / `broadcast` to them; it
receives via an optional `local` MessageQueue (typically TCP-server-backed)
that peers push into. The model is **push-only**: a node sends to a named
peer, and receivers just `subscribe` locally -- there is no reaching into a
peer's private topics (that direction is request-reply; use RPC).

A node needs a `local` queue **only if it receives**. A pure sender does
not.

```python
from eventforge import MessageQueue, RemoteQueue
from eventforge.transports.tcp import TCPServerTransport

# --- Worker: RECEIVES, so it listens on a port and subscribes locally. ---
# (TCPServerTransport must be .start()ed before use.)
worker_srv = TCPServerTransport(host="0.0.0.0", port=9001)
worker_srv.start()
worker = RemoteQueue("worker-1", local=MessageQueue(transport=worker_srv))

@worker.on("work")
def run(msg):
    print(f"worker got: {msg.payload}")

# --- Coordinator: only SENDS, so it needs no local queue at all. ---
coord = RemoteQueue("coordinator")
coord.connect("worker-1", host="127.0.0.1", port=9001)  # own a TCP link by address

coord.send("worker-1", "work", {"task": 42})  # push to one peer
# -> worker got: {'task': 42}

coord.broadcast("work", {"task": 99})          # push to ALL connected peers
print(coord.peers)                             # ['worker-1']
```

To make it bidirectional, give the coordinator a `local` too and have the
worker `send` results back. To *pull* from a peer's topic, use
[Execution / RPC](#execution) instead -- `RemoteQueue` is push-only by
design.

## Execution

Request-reply: one call, one returned value.

### LocalProcedureCaller (local)

`LocalProcedureCaller` runs a callable in-process and hands back its value.
(`Executor` is a deprecated alias kept for back-compat -- prefer
`LocalProcedureCaller`.) Three modes: `SEQUENTIAL` (run inline, the
default), `THREAD` (thread pool, I/O-bound), `PROCESS` (process pool,
CPU-bound).

The high-level entry point is `.call(target, *args, **kwargs)`, which
returns the unwrapped value: in `SEQUENTIAL` mode it runs the callable
directly; otherwise it submits to the pool and waits for the result's value.

```python
from eventforge import LocalProcedureCaller, ExecutionMode

def heavy_task(n):
    return sum(range(n))

# One call, one value -- this is the Caller surface.
caller = LocalProcedureCaller(mode=ExecutionMode.THREAD, max_workers=4)
print(caller.call(heavy_task, 1_000_000))   # 499999500000
```

For finer control, `submit` / `result` / `map` expose the `TaskResult`
(`.value` / `.error` / `.status` / `.execution_time`):

```python
from eventforge import LocalProcedureCaller, ExecutionMode

def heavy_task(n):
    return sum(range(n))

# Submit a job and fetch its TaskResult by id.
with LocalProcedureCaller(mode=ExecutionMode.THREAD, max_workers=4) as caller:
    task_id = caller.submit(heavy_task, 1_000_000)
    result = caller.result(task_id)
    print(result.value)

# Process pool for CPU-bound work, mapped over an iterable.
with LocalProcedureCaller(mode=ExecutionMode.PROCESS, max_workers=4) as caller:
    for r in caller.map(heavy_task, [100_000, 200_000, 300_000]):
        print(r.value)
```

`submit` returns a `task_id`; `result(task_id)` blocks for the
`TaskResult`. In `SEQUENTIAL` mode the work runs inline at submit time.
Async variants (`submit_async`, `result_async`, `map_async`) mirror the
sync API.

### RPC (remote)

RPC is request-reply across a queue: `RPCServer` registers methods,
`RPCClient.call(method, *args)` invokes them and returns the result.
`method` may be a name string *or* a callable (in which case its
`__name__` is used as the remote method name), so an `RPCClient` is the
remote `Caller` -- structurally interchangeable with a
`LocalProcedureCaller`. Run it over a TCP-backed `MessageQueue` to reach
another process or machine; the client API is identical whether the server
is in-process or across the network.

```python
from eventforge import MessageQueue, RPCServer, RPCClient

queue = MessageQueue()

# Server
server = RPCServer(queue, service_name="calculator")

@server.register()
def add(a: int, b: int) -> int:
    return a + b

@server.register()
def multiply(a: int, b: int) -> int:
    return a * b

server.serve(blocking=False)  # subscribe + return; True blocks the thread

# Client
client = RPCClient(queue, service_name="calculator")
print(client.call("add", 10, 20))   # 30
print(client.multiply(5, 6))        # 30 (dynamic method access)

server.stop()
```

`RoundRobinRPCClient([client1, client2, ...])` spreads `call`s across a
pool of clients (each typically pointed at a different worker); `with_retry`
wraps a client with exponential-backoff retries. Both keep the same
`call(method, *args)` surface.

### The Caller protocol (the unifier)

`Caller` is a `@runtime_checkable` `Protocol` with a single method,
`call(target, *args, **kwargs) -> value`. `LocalProcedureCaller` and
`RPCClient` both satisfy it structurally, so request-reply is one shape at
two distances:

```
LocalProcedureCaller : RPCClient :: Local : Remote Procedure Call
```

Anything that accepts a `Caller` -- notably `@task(caller=...)` -- can target
either transparently: run the work in-process or dispatch it to a remote
worker by swapping the `Caller`, with no other change.

## Composing with @task

`@task` is **not** a layer -- it is a facade. It composes a `Caller`, an
optional `MessageQueue`, and `Observers` into a single callable that you can
invoke directly *or* trigger by publishing to its topic. The `caller=`
parameter (a `Caller`) decides *where* the work runs; both invocation paths
run the identical lifecycle.

```python
from eventforge import (
    task, MessageQueue, LocalProcedureCaller, ExecutionMode, TimingMeter
)

queue = MessageQueue()
caller = LocalProcedureCaller(mode=ExecutionMode.THREAD)
timing = TimingMeter()

@task(
    queue=queue,             # pub-sub wiring (subscribe topic + publish result)
    topic="process.data",
    caller=caller,           # the Caller: local LocalProcedureCaller here
    on_execute=[timing],     # observers (cross-cutting)
    on_success=lambda ctx: print(f"Done: {ctx.result}"),
)
def process_data(data):
    return data.upper()

# Direct call -- runs locally through the LocalProcedureCaller, returns the result.
result = process_data("hello")   # "HELLO"

# Queue trigger -- same execution path, same observers.
queue.publish("process.data", "world")

print(timing.stats)              # {'count': 2, 'avg': ..., ...}
```

(`executor=` is accepted as a deprecated alias for `caller=`; prefer
`caller=`.)

Running the same work remotely is a one-parameter flip on the *same*
function: keep the body as the reference implementation, expose it on a
worker via `RPCServer` (or `python -m eventforge.worker`, see
[Deployment](#deployment)), and point `caller=` at an `RPCClient`. Because
`RPCClient` is also a `Caller`, `@task` dispatches the function to the remote
worker by its `__name__` instead of running the body locally:

```python
from eventforge import task, MessageQueue, RPCClient
from eventforge.transports.tcp import TCPClientTransport

transport = TCPClientTransport(host="gpu-host", port=9090)
transport.connect()
remote = RPCClient(MessageQueue(transport=transport), service_name="data")

# Same function, remote Caller -> dispatched to a remote/containerized worker.
@task(caller=remote)
def process_data(data):
    return data.upper()        # reference impl; not run locally

result = process_data("world")  # runs on the worker, by name "process_data"
```

So `@task(caller=LocalProcedureCaller())` runs the body in-process while
`@task(caller=RPCClient(...))` dispatches the identical function to a remote
worker by name -- `LocalProcedureCaller : RPCClient :: Local : Remote
Procedure Call`. `@task` simply bundles the chosen `Caller` + queue +
observers so you do not wire them by hand.

## Observers

Observers are cross-cutting: they measure or log a task without being part
of its logic. Attach them via `@task(on_execute=[...])` or the standalone
`@observe(...)` decorator.

```python
from eventforge import task, TimingMeter, MetricsMeter, observe

timing = TimingMeter(threshold=1.0)  # alert if > 1s
metrics = MetricsMeter()

@task(on_execute=[timing, metrics])
def my_task(x):
    return x * 2

my_task(21)
my_task(42)

print(timing.stats)   # {'count': 2, 'avg': ..., 'min': ..., 'max': ...}
print(metrics.stats)  # {'calls': 2, 'successes': 2, 'failures': 0}

# Or @observe on any plain function:
@observe(timing, metrics)
def simple_function(x):
    return x + 1
```

Built-in observers:

- `TimingMeter` -- execution timing with threshold alerts
- `MetricsMeter` -- call counts, success/failure rates
- `MemoryMeter` -- memory usage tracking
- `CPUMeter` -- CPU usage tracking
- `Meter` -- running averages (for training loops)
- `LoggingReporter` -- structured logging

The core primitive underneath is `Observable` / `Eventful` / `Dispatcher`
(`BroadcastDispatcher`, `RoundRobinDispatcher`, `ConcurrentDispatcher`,
`LeastLoadedDispatcher`) plus `Node` -- see [docs/observers.md](docs/observers.md).

## Deployment

A *server* node runs the generic worker entrypoint against a handler
module; a *demander* (client) connects with `RPCClient` /
`RoundRobinRPCClient` over the same `service_name` and round-robins across
the server pool.

```bash
python -m eventforge.worker --import handlers --service math --port 9090
# handlers.py exposes:  HANDLERS = {"compute": compute};  SERVICE_NAME = "math"
```

The module must define a non-empty `HANDLERS` dict of `{name: callable}`
(and optionally `SERVICE_NAME`); the entrypoint binds a TCP server, builds
the `MessageQueue` + `RPCServer`, and registers every handler -- no
transport boilerplate.

Run a whole topology on one machine (servers + a demander):

```bash
docker compose -f deploy/docker-compose.yml up --build
```

```
demander  --RPC (JSON/TCP)-->  server1
                          \-->  server2   (round-robin, client-side)
                          \-->  server3
```

**Scope, honestly:** this is a push-only RPC compute-worker pool for a
*trusted* network -- request/response, client-side load balancing (the
demander needs every server address; no broker, no discovery), and the TCP
transport has no auth/TLS. It is **not** a durable job queue: `WorkQueue`'s
competing-consumer / ack-nack / DLQ machinery is in-process only and does
not cross containers. For brokered, durable cross-machine queues use Celery
/ RQ / Dramatiq. eventforge's niche is scaling code *already* on the
eventforge + registry-pattern stack without a second framework. Full guide
and the `eventforge.worker` contract: [`deploy/README.md`](deploy/README.md).
`deploy/` also ships a Dockerfile and an Apptainer definition.

## API Reference

Compact per-type signatures. See `docs/` for full detail.

### Transport

```python
MemoryTransport(max_queue_size=1000)              # in-process (default)
TCPServerTransport(host="127.0.0.1", port=9090)   # call .start()
TCPClientTransport(host="localhost", port=9090)   # call .connect()
# ABC: send / receive / receive_async / subscribe / unsubscribe / close
```

### MessageQueue

```python
queue = MessageQueue(transport=None)              # default MemoryTransport

queue.publish(topic, payload, **headers)          # -> message_id
queue.subscribe(topic, handler)                   # -> handler_id
queue.on(topic)                                   # decorator or on(topic, fn)
queue.unsubscribe(handler_id)                     # -> bool
queue.receive(topic, timeout=None)                # -> Message | None
queue.request(topic, payload, timeout=30.0, **h)  # -> Message | None
queue.reply(original, payload, **headers)         # -> message_id
queue.close()
```

### RemoteQueue

```python
remote = RemoteQueue(node_id, *, local=None)      # local = MessageQueue you receive on

remote.connect(node_id, host, port)               # open + own a TCP link to a peer
remote.disconnect(node_id)                        # -> bool
remote.send(node_id, topic, payload, **headers)   # push to ONE peer -> msg_id
remote.broadcast(topic, payload, **headers)       # push to ALL peers -> {node: msg_id}
remote.subscribe(topic, handler)                  # receive locally -> sub_id
remote.on(topic)                                  # decorator form of subscribe
remote.peers                                      # connected peer node ids
remote.close()
```

### Caller (protocol)

```python
# Structural protocol unifying local and remote request-reply.
# LocalProcedureCaller and RPCClient both satisfy it.
class Caller(Protocol):
    def call(self, target, *args, **kwargs): ...   # -> value
```

### LocalProcedureCaller (deprecated alias: Executor)

```python
caller = LocalProcedureCaller(mode=ExecutionMode.SEQUENTIAL, max_workers=4)

value = caller.call(func, *args, **kwargs)        # Caller surface -> value
task_id = caller.submit(func, *args, **kwargs)    # -> task_id
result = caller.result(task_id, timeout=None)     # -> TaskResult
results = caller.map(func, items, timeout=None)   # -> list[TaskResult]
caller.start(); caller.stop(wait=True)            # also a context manager
# ExecutionMode: SEQUENTIAL / THREAD / PROCESS
# Executor is a deprecated alias for LocalProcedureCaller.
```

### RPC

```python
# Server
server = RPCServer(queue, executor=None, service_name="rpc")
server.register(name=None)(func)                  # decorator
server.add_method(name, func)
server.serve(blocking=True)                       # blocking=False returns immediately
server.stop()

# Client (also a Caller: satisfies the Caller protocol)
client = RPCClient(queue, service_name="rpc", timeout=30.0)
client.call(method, *args, timeout=None, **kwargs)   # method: name str OR callable
                                                     #   (callable -> uses __name__) -> result
client.method_name(*args)                            # dynamic access
RoundRobinRPCClient([client1, client2, ...])         # client-side load balance
with_retry(client, max_retries=3, ...)               # backoff wrapper
```

### Task

```python
@task(
    queue=None,           # MessageQueue for pub-sub integration
    topic=None,           # topic name (defaults to function name)
    caller=None,          # Caller: LocalProcedureCaller (local, default) or
                          #   RPCClient (remote dispatch by func.__name__)
    executor=None,        # deprecated alias for caller
    on_execute=None,      # list of observers
    on_success=None,      # Callable[[TaskContext], None]
    on_failure=None,      # Callable[[TaskContext], None]
    on_complete=None,     # Callable[[TaskContext], None]
    publish_result=True,  # auto-publish to {topic}.success / {topic}.failure
    max_instances=None,   # concurrency cap (None = unlimited)
    instance_timeout=None,
)
def my_task(x): ...

my_task(21)               # direct call -> result
my_task.state            # SharedState across invocations
my_task.pool.stats       # TaskPool stats when max_instances is set
```

## License

MIT
