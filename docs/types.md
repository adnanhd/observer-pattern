# Types

Pydantic models for messages, tasks, and RPC.

## Overview

CallPyBack uses Pydantic v2 models for:
- Type validation
- Serialization/deserialization
- API documentation

## Message

Message for pub-sub communication:

```python
from eventforge import Message

msg = Message(
    topic="events.user.created",
    payload={"id": 1, "name": "Alice"},
    headers={"priority": "high"},
)

print(msg.id)              # Auto-generated UUID
print(msg.topic)           # "events.user.created"
print(msg.payload)         # {"id": 1, "name": "Alice"}
print(msg.headers)         # {"priority": "high"}
print(msg.timestamp)       # datetime (auto-set)
print(msg.reply_to)        # Optional[str]
print(msg.correlation_id)  # Optional[str]
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | UUID | Unique message identifier |
| `topic` | `str` | required | Topic for routing |
| `payload` | `Any` | required | Message content |
| `headers` | `Dict[str, Any]` | `{}` | Custom headers |
| `timestamp` | `datetime` | now (UTC) | Creation time |
| `reply_to` | `str` | `None` | Reply topic for request-reply |
| `correlation_id` | `str` | `None` | Correlation identifier |

## TaskStatus

Enum for task execution status:

```python
from eventforge import TaskStatus

TaskStatus.PENDING     # Task queued, not started
TaskStatus.RUNNING     # Task currently executing
TaskStatus.COMPLETED   # Task finished successfully
TaskStatus.FAILED      # Task failed with error
TaskStatus.CANCELLED   # Task was cancelled
```

## TaskRequest

Request to execute a task:

```python
from eventforge import TaskRequest

request = TaskRequest(
    func_name="compute",
    args=(10, 20),
    kwargs={"option": True},
    priority=1,
    timeout=30.0,
)

print(request.id)         # Auto-generated UUID
print(request.func_name)  # "compute"
print(request.args)       # (10, 20)
print(request.kwargs)     # {"option": True}
print(request.priority)   # 1
print(request.timeout)    # 30.0
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | UUID | Unique request identifier |
| `func_name` | `str` | required | Function name |
| `args` | `Tuple[Any, ...]` | `()` | Positional arguments |
| `kwargs` | `Dict[str, Any]` | `{}` | Keyword arguments |
| `priority` | `int` | `0` | Execution priority |
| `timeout` | `float` | `None` | Timeout in seconds |

## TaskResult

Result of task execution:

```python
from eventforge import TaskResult, TaskStatus

# Success result
result = TaskResult(
    task_id="abc123",
    status=TaskStatus.COMPLETED,
    value=42,
    execution_time=0.5,
    worker_id="thread-1",
)

print(result.is_success)  # True
print(result.is_failure)  # False
print(result.value)       # 42

# Failure result
error_result = TaskResult(
    task_id="abc123",
    status=TaskStatus.FAILED,
    error="Division by zero",
    error_type="ZeroDivisionError",
    execution_time=0.1,
)

print(error_result.is_failure)  # True
print(error_result.error)       # "Division by zero"
print(error_result.error_type)  # "ZeroDivisionError"
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `task_id` | `str` | required | Task identifier |
| `status` | `TaskStatus` | required | Execution status |
| `value` | `Any` | `None` | Return value (on success) |
| `error` | `str` | `None` | Error message (on failure) |
| `error_type` | `str` | `None` | Exception type name |
| `execution_time` | `float` | `0.0` | Duration in seconds |
| `worker_id` | `str` | `""` | Worker identifier |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `is_success` | `bool` | `status == COMPLETED` |
| `is_failure` | `bool` | `status == FAILED` |

## RPCRequest

RPC method call request:

```python
from eventforge import RPCRequest

request = RPCRequest(
    method="add",
    args=(10, 20),
    kwargs={},
    timeout=30.0,
)

print(request.id)       # Auto-generated UUID
print(request.method)   # "add"
print(request.args)     # (10, 20)
print(request.kwargs)   # {}
print(request.timeout)  # 30.0
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | UUID | Unique request identifier |
| `method` | `str` | required | Method name to call |
| `args` | `Tuple[Any, ...]` | `()` | Positional arguments |
| `kwargs` | `Dict[str, Any]` | `{}` | Keyword arguments |
| `timeout` | `float` | `None` | Request timeout |

## RPCResponse

RPC method call response:

```python
from eventforge import RPCResponse

# Success response
response = RPCResponse(
    id="resp123",
    request_id="req123",
    result=30,
)

print(response.is_success)  # True
print(response.result)      # 30

# Error response
error_response = RPCResponse(
    id="resp456",
    request_id="req456",
    error="Method not found",
    error_type="MethodNotFound",
)

print(error_response.is_success)  # False
print(error_response.error)       # "Method not found"
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | required | Response identifier |
| `request_id` | `str` | required | Matching request ID |
| `result` | `Any` | `None` | Return value |
| `error` | `str` | `None` | Error message |
| `error_type` | `str` | `None` | Error type name |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `is_success` | `bool` | `error is None` |

## Subscription

Topic subscription:

```python
from eventforge.types import Subscription

sub = Subscription(
    topic="events.*",
    pattern=True,  # Topic is a pattern
)

print(sub.id)       # Auto-generated UUID
print(sub.topic)    # "events.*"
print(sub.pattern)  # True
```

## Serialization

All models support JSON serialization:

```python
from eventforge import Message
import json

msg = Message(topic="test", payload={"key": "value"})

# To dict
data = msg.model_dump()

# To JSON
json_str = msg.model_dump_json()

# From dict
msg2 = Message.model_validate(data)

# From JSON
msg3 = Message.model_validate_json(json_str)
```

## Custom Validation

Extend types with custom validation:

```python
from pydantic import BaseModel, field_validator
from eventforge import Message

class ValidatedMessage(Message):
    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v):
        if not v.startswith("app."):
            raise ValueError("Topic must start with 'app.'")
        return v

# This works
msg = ValidatedMessage(topic="app.users", payload={})

# This raises ValidationError
msg = ValidatedMessage(topic="invalid", payload={})
```

## Type Hints

All types are fully typed for IDE support:

```python
from eventforge import Message, TaskResult, TaskStatus
from typing import Optional

def process_message(msg: Message) -> Optional[TaskResult]:
    if not msg.payload:
        return None
    
    return TaskResult(
        task_id=msg.id,
        status=TaskStatus.COMPLETED,
        value=msg.payload,
    )
```
