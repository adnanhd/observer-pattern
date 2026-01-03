# Message Queue

Thread-safe pub-sub message queue with Pydantic validation.

## Overview

`MessageQueue` provides publish-subscribe messaging with:
- Topic-based routing with pattern matching
- Request-reply pattern support
- Async/await support
- Pluggable transports

## Basic Usage

```python
from callpyback import MessageQueue

queue = MessageQueue()

# Subscribe to topic
@queue.on("events.user")
def handle_user_event(msg):
    print(f"User event: {msg.payload}")

# Publish message
queue.publish("events.user", {"action": "login", "user_id": 123})
```

## Topic Patterns

Subscribe to multiple topics using wildcard patterns:

```python
# Match any event under "events."
@queue.on("events.*")
def handle_all_events(msg):
    print(f"{msg.topic}: {msg.payload}")

queue.publish("events.user", {"action": "login"})     # Matches
queue.publish("events.order", {"id": 456})            # Matches
queue.publish("other.topic", {"data": "x"})           # Does not match
```

## Request-Reply Pattern

Synchronous request-response:

```python
# Server side
@queue.on("math.add")
def add_handler(msg):
    a, b = msg.payload["a"], msg.payload["b"]
    queue.reply(msg, a + b)

# Client side
response = queue.request("math.add", {"a": 10, "b": 20}, timeout=5.0)
print(response.payload)  # 30
```

## Async Support

```python
import asyncio
from callpyback import MessageQueue

async def main():
    queue = MessageQueue()
    
    @queue.on("async.task")
    def handler(msg):
        queue.reply(msg, msg.payload * 2)
    
    # Async publish
    await queue.publish_async("events.test", {"data": "value"})
    
    # Async request-reply
    response = await queue.request_async("async.task", 21, timeout=5.0)
    print(response.payload)  # 42
    
    # Async receive
    msg = await queue.receive_async("some.topic", timeout=1.0)

asyncio.run(main())
```

## Message Structure

Messages are Pydantic models with the following fields:

```python
from callpyback import Message

msg = Message(
    topic="events.user",
    payload={"action": "login"},
    headers={"priority": "high"},
)

print(msg.id)           # Auto-generated UUID
print(msg.topic)        # "events.user"
print(msg.payload)      # {"action": "login"}
print(msg.headers)      # {"priority": "high"}
print(msg.timestamp)    # datetime
print(msg.reply_to)     # Optional reply topic
print(msg.correlation_id)  # Optional correlation ID
```

## API Reference

### MessageQueue

```python
class MessageQueue:
    def __init__(self, transport: Optional[Transport] = None):
        """Create queue with optional transport (defaults to MemoryTransport)."""
    
    def publish(self, topic: str, payload: Any, **headers) -> str:
        """Publish message. Returns message_id."""
    
    async def publish_async(self, topic: str, payload: Any, **headers) -> str:
        """Publish message asynchronously."""
    
    def subscribe(self, topic: str, handler: Callable[[Message], None]) -> str:
        """Subscribe to topic. Returns handler_id."""
    
    def unsubscribe(self, handler_id: str) -> bool:
        """Unsubscribe handler."""
    
    def on(self, topic: str) -> Callable:
        """Decorator for subscribing handlers."""
    
    def receive(self, topic: str, timeout: float = None) -> Optional[Message]:
        """Receive next message (blocking)."""
    
    async def receive_async(self, topic: str, timeout: float = None) -> Optional[Message]:
        """Receive next message (async)."""
    
    def request(self, topic: str, payload: Any, timeout: float = 30.0, **headers) -> Optional[Message]:
        """Send request and wait for response."""
    
    async def request_async(self, topic: str, payload: Any, timeout: float = 30.0, **headers) -> Optional[Message]:
        """Async request-reply."""
    
    def reply(self, original: Message, payload: Any, **headers) -> str:
        """Reply to a message."""
    
    def close(self) -> None:
        """Close queue and transport."""
```

## Examples

### Event Bus

```python
from callpyback import MessageQueue

queue = MessageQueue()

# Multiple handlers for same topic
@queue.on("user.created")
def send_welcome_email(msg):
    user = msg.payload
    print(f"Sending welcome email to {user['email']}")

@queue.on("user.created")
def create_default_settings(msg):
    user = msg.payload
    print(f"Creating default settings for user {user['id']}")

@queue.on("user.created")
def log_user_creation(msg):
    user = msg.payload
    print(f"User created: {user['id']}")

# Trigger all handlers
queue.publish("user.created", {"id": 1, "email": "alice@example.com"})
```

### Worker Queue

```python
from callpyback import MessageQueue
import threading

queue = MessageQueue()

def worker():
    while True:
        msg = queue.receive("tasks", timeout=1.0)
        if msg:
            print(f"Processing task: {msg.payload}")
            # Process task...
            queue.publish("tasks.completed", {"task_id": msg.payload["id"]})

# Start workers
for i in range(4):
    threading.Thread(target=worker, daemon=True).start()

# Submit tasks
for i in range(10):
    queue.publish("tasks", {"id": i, "type": "process_data"})
```
