# RPC

Remote Procedure Call over message queue.

## Overview

CallPyBack provides RPC functionality via:
- `RPCServer` - Registers and handles method calls
- `RPCClient` - Makes remote method calls

Both use `MessageQueue` as the transport layer.

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
        """Create RPC server."""
    
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
        """Call remote method synchronously."""
    
    async def call_async(self, method: str, *args, timeout: float = None, **kwargs) -> Any:
        """Call remote method asynchronously."""
    
    def __getattr__(self, name: str) -> Callable:
        """Allow client.method_name(*args) syntax."""
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
