# RPC

Remote Procedure Call over message queue.

RPC is the **remote request-reply** layer -- the network counterpart to the
local [`LocalProcedureCaller`](executor.md). Both satisfy the
[`Caller` protocol](executor.md#the-caller-protocol) and follow the same
call-and-return shape; RPC just puts a `MessageQueue` (typically TCP-backed)
between caller and callee:

```
LocalProcedureCaller : RPCClient :: Local : Remote Procedure Call
```

Because `RPCClient` is a `Caller`, it can be passed to
[`@task(caller=...)`](task.md) to dispatch a decorated function to a remote
worker -- see [Running Task Logic Remotely](#running-task-logic-remotely).

## Overview

eventforge provides RPC functionality via:
- `RPCServer` - Registers and handles method calls
- `RPCClient` - Makes remote method calls

Both use `MessageQueue` as the transport layer. Run them over a TCP
transport (`TCPServerTransport` / `TCPClientTransport`) to reach another
process or machine; the client API is identical whether the server is
in-process or across the network.

## Basic Usage

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

server.serve(blocking=False)

# Client
client = RPCClient(queue, service_name="calculator")

result = client.call("add", 10, 20)
print(result)  # 30

result = client.call("multiply", 5, 6)
print(result)  # 30

server.stop()
```

## Dynamic Method Access

Call methods using attribute syntax:

```python
client = RPCClient(queue, service_name="calculator")

# These are equivalent:
client.call("add", 10, 20)
client.add(10, 20)

client.call("multiply", 5, 6)
client.multiply(5, 6)
```

## Calling by Name or by Callable

`RPCClient.call(method, *args)` accepts `method` as either a name string
**or** a callable. When given a callable, the client uses its `__name__` as
the remote method name -- the callable's body is never run locally, it just
supplies the name (a "reference implementation"):

```python
def process_data(data):
    return data.upper()          # reference impl; runs on the worker

# These dispatch to the same remote method "process_data":
client.call("process_data", "world")
client.call(process_data, "world")   # uses process_data.__name__
```

This is exactly how `RPCClient` satisfies the
[`Caller` protocol](executor.md#the-caller-protocol) and why it works as
`@task(caller=client)`: `@task` calls `caller.call(self.func, ...)`, and the
`RPCClient` turns `self.func` into its `__name__` for remote dispatch.

## Custom Method Names

Register methods with custom names:

```python
@server.register(name="sum")
def add_numbers(a, b):
    return a + b

# Client calls "sum", not "add_numbers"
result = client.call("sum", 1, 2)
```

## Error Handling

```python
@server.register()
def divide(a: int, b: int) -> float:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

server.serve(blocking=False)

try:
    result = client.call("divide", 10, 0)
except Exception as e:
    print(e)  # "ValueError: Cannot divide by zero"
```

## Timeouts

```python
# Client-level timeout
client = RPCClient(queue, service_name="slow_service", timeout=5.0)

# Per-call timeout
result = client.call("slow_method", timeout=10.0)
```

## Async Support

```python
import asyncio
from eventforge import MessageQueue, RPCServer, RPCClient

async def main():
    queue = MessageQueue()
    
    server = RPCServer(queue, service_name="async_service")
    
    @server.register()
    def compute(x):
        return x ** 2
    
    # Async serve
    asyncio.create_task(server.serve_async())
    
    client = RPCClient(queue, service_name="async_service")
    
    # Async call
    result = await client.call_async("compute", 10)
    print(result)  # 100

asyncio.run(main())
```

## Multiple Services

Run multiple RPC services on the same queue:

```python
queue = MessageQueue()

# Math service
math_server = RPCServer(queue, service_name="math")

@math_server.register()
def add(a, b):
    return a + b

# String service
string_server = RPCServer(queue, service_name="string")

@string_server.register()
def concat(a, b):
    return a + b

math_server.serve(blocking=False)
string_server.serve(blocking=False)

# Clients
math_client = RPCClient(queue, service_name="math")
string_client = RPCClient(queue, service_name="string")

print(math_client.add(1, 2))        # 3
print(string_client.concat("a", "b"))  # "ab"
```

## Load Balancing and Retries

`RoundRobinRPCClient` spreads calls across a pool of `RPCClient` instances
(each typically pointed at a different worker); `with_retry` wraps a client
with exponential-backoff retries. Both keep the same `call(name, *args)`
surface.

```python
from eventforge import MessageQueue, RPCClient, RoundRobinRPCClient, with_retry
from eventforge.transports.tcp import TCPClientTransport

clients = []
for port in (9090, 9091, 9092):
    transport = TCPClientTransport(host="127.0.0.1", port=port)
    transport.connect()
    clients.append(RPCClient(MessageQueue(transport=transport), service_name="compute"))

pool = RoundRobinRPCClient(clients)
result = pool.call("heavy_computation", 100000)  # round-robined across workers

# Wrap any client to retry on TimeoutError / ConnectionError.
robust = with_retry(clients[0], max_retries=3, backoff_initial=0.1, backoff_factor=2.0)
result = robust.call("heavy_computation", 100000)
```

## Running Task Logic Remotely

`RPCClient` is how you dispatch a `@task`-decorated function to a remote
worker. Because `RPCClient` is a [`Caller`](executor.md#the-caller-protocol),
you pass it directly as `@task(caller=client)`: `@task` then calls
`client.call(func, ...)`, the client dispatches by `func.__name__`, and the
worker runs the registered function and returns the value. The local body is
the reference implementation and is not executed locally.

```python
from eventforge import task, MessageQueue, RPCClient
from eventforge.transports.tcp import TCPClientTransport

transport = TCPClientTransport(host="gpu-host", port=9090)
transport.connect()
client = RPCClient(MessageQueue(transport=transport), service_name="compute")

@task(caller=client)
def heavy_computation(n):
    return sum(i ** 2 for i in range(n))   # reference impl; runs on the worker

result = heavy_computation(100000)         # dispatched by name "heavy_computation"
```

Swap `caller=client` for `caller=LocalProcedureCaller()` and the identical
function runs in-process instead. Register the matching function on the
server side (by the same name the client calls). See
[Task Decorator](task.md) and `examples/07_distributed_workers.py`.

For a no-boilerplate server, point the generic worker entrypoint at a module
exposing a `HANDLERS` dict:

```bash
python -m eventforge.worker --import handlers --service compute --port 9090
# handlers.py:  HANDLERS = {"heavy_computation": heavy_computation}
```

## API Reference

### RPCServer

```python
class RPCServer:
    def __init__(
        self,
        queue: MessageQueue,
        executor: Optional[LocalProcedureCaller] = None,
        service_name: str = "rpc",
    ):
        """Create RPC server (executor defaults to a LocalProcedureCaller)."""
    
    def register(self, name: str = None) -> Callable:
        """Decorator to register RPC method."""
    
    def add_method(self, name: str, func: Callable) -> None:
        """Register method directly."""
    
    def serve(self, blocking: bool = True) -> None:
        """Start serving requests."""
    
    async def serve_async(self) -> None:
        """Serve requests asynchronously."""
    
    def stop(self) -> None:
        """Stop serving."""
```

### RPCClient

`RPCClient` satisfies the [`Caller` protocol](executor.md#the-caller-protocol)
(its `call` is the `Caller.call` method), so it can be used as
`@task(caller=client)`.

```python
class RPCClient:
    def __init__(
        self,
        queue: MessageQueue,
        service_name: str = "rpc",
        timeout: float = 30.0,
    ):
        """Create RPC client."""

    def call(self, method: str | Callable, *args, timeout: float = None, **kwargs) -> Any:
        """Call remote method synchronously.

        method may be a name string OR a callable; a callable's __name__ is
        used as the remote method name (its body is not run locally).
        """

    async def call_async(self, method: str, *args, timeout: float = None, **kwargs) -> Any:
        """Call remote method asynchronously."""
    
    def __getattr__(self, name: str) -> Callable:
        """Allow client.method_name(*args) syntax."""
```

### RoundRobinRPCClient

```python
class RoundRobinRPCClient:
    def __init__(self, clients: list[RPCClient]):
        """Dispatch call() round-robin across a pool of RPCClients."""

    def call(self, method: str, *args, timeout: float = None, **kwargs) -> Any: ...
```

### with_retry

```python
def with_retry(
    client: RPCClient,
    *,
    max_retries: int = 3,
    backoff_initial: float = 0.1,
    backoff_factor: float = 2.0,
    retry_on: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError),
) -> RPCClient:
    """Wrap a client so each call() retries with exponential backoff."""
```

### Request/Response Types

```python
class RPCRequest(BaseModel):
    id: str                    # Auto-generated UUID
    method: str                # Method name
    args: Tuple[Any, ...]      # Positional arguments
    kwargs: Dict[str, Any]     # Keyword arguments
    timeout: Optional[float]   # Request timeout

class RPCResponse(BaseModel):
    id: str                    # Response UUID
    request_id: str            # Matching request ID
    result: Any                # Return value
    error: Optional[str]       # Error message
    error_type: Optional[str]  # Exception type
    
    @property
    def is_success(self) -> bool: ...
```

## Examples

### Microservice Pattern

```python
from eventforge import MessageQueue, RPCServer, RPCClient

# Shared queue (in production, use Redis/ZMQ transport)
queue = MessageQueue()

# User service
user_server = RPCServer(queue, service_name="users")

users_db = {}

@user_server.register()
def create_user(name: str, email: str) -> dict:
    user_id = len(users_db) + 1
    users_db[user_id] = {"id": user_id, "name": name, "email": email}
    return users_db[user_id]

@user_server.register()
def get_user(user_id: int) -> dict:
    return users_db.get(user_id)

user_server.serve(blocking=False)

# Order service that depends on user service
order_server = RPCServer(queue, service_name="orders")
user_client = RPCClient(queue, service_name="users")

@order_server.register()
def create_order(user_id: int, items: list) -> dict:
    user = user_client.get_user(user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")
    return {"user": user, "items": items}

order_server.serve(blocking=False)

# Gateway
order_client = RPCClient(queue, service_name="orders")

user = user_client.create_user("Alice", "alice@example.com")
order = order_client.create_order(user["id"], ["item1", "item2"])
print(order)
```

### Worker Pool

```python
from eventforge import MessageQueue, RPCServer, LocalProcedureCaller, ExecutionMode
import threading

queue = MessageQueue()
caller = LocalProcedureCaller(mode=ExecutionMode.PROCESS, max_workers=4)

server = RPCServer(queue, executor=caller, service_name="compute")

@server.register()
def heavy_computation(n: int) -> int:
    """CPU-intensive task."""
    return sum(i ** 2 for i in range(n))

# Start server in background
threading.Thread(target=lambda: server.serve(blocking=True), daemon=True).start()

# Multiple clients can call concurrently
client = RPCClient(queue, service_name="compute")

results = []
for n in [100000, 200000, 300000]:
    result = client.heavy_computation(n)
    results.append(result)

print(results)
```
