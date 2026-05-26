# RPC

Remote Procedure Call over message queue.

RPC is the **remote request-reply** layer: you register a function on an
`RPCServer` and call it **by name** from an `RPCClient`. It puts a
`MessageQueue` (typically TCP-backed) between client and server.

`RPCClient.call` takes a method-NAME string, not a callable: the function
lives on the server. To run a `@task`-decorated function remotely, register
it on a server and have the client call it by name -- see
[Running Task Logic on a Server](#running-task-logic-on-a-server).

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

## Calling by Name

`RPCClient.call(method, *args)` takes `method` as a name **string** only --
the name of a method registered on the server. The callable itself lives on
the server; the client just names it:

```python
# The server registered "process_data"; the client calls it by that name.
client.call("process_data", "world")   # -> runs process_data ON the server
```

There is no callable-accepting form: `RPCClient.call` always takes a
method-name string, and the function lives on the server.

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

## Running Task Logic on a Server

To run logic remotely, define the function **on the server** (where it
actually executes) and call it **by name** from the client. The client is a
plain `RPCClient.call("name", ...)` -- no `@task`, no stub, no callable
passed across the wire.

```python
from eventforge import task, MessageQueue, RPCServer, RPCClient, TimingMeter
from eventforge.transports.tcp import TCPServerTransport, TCPClientTransport

# SERVER: define heavy_computation where it runs; @task gives it observability.
@task(on_execute=[TimingMeter()])
def heavy_computation(n):
    return sum(i ** 2 for i in range(n))

server_q = MessageQueue(transport=TCPServerTransport(host="0.0.0.0", port=9090))
server = RPCServer(server_q, service_name="compute")
server.add_method("heavy_computation", heavy_computation)   # or @server.register("heavy_computation")
server.serve(blocking=False)

# CLIENT: plain call by name -- runs heavy_computation ON the server.
transport = TCPClientTransport(host="gpu-host", port=9090)
transport.connect()
client = RPCClient(MessageQueue(transport=transport), service_name="compute")
result = client.call("heavy_computation", 100000)
```

See [Task Decorator](task.md) and `examples/07_distributed_workers.py`.

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
        executor: Optional[Executor] = None,
        service_name: str = "rpc",
    ):
        """Create RPC server (executor defaults to an Executor)."""
    
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

`RPCClient.call` takes a method-name string, not a callable: the function
lives on the server.

```python
class RPCClient:
    def __init__(
        self,
        queue: MessageQueue,
        service_name: str = "rpc",
        timeout: float = 30.0,
    ):
        """Create RPC client."""

    def call(self, method: str, *args, timeout: float = None, **kwargs) -> Any:
        """Call a remote method by name synchronously.

        method is the name (string) of a method registered on the server.
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
from eventforge import MessageQueue, RPCServer, Executor, ExecutionMode
import threading

queue = MessageQueue()
executor = Executor(mode=ExecutionMode.PROCESS, max_workers=4)

server = RPCServer(queue, executor=executor, service_name="compute")

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
