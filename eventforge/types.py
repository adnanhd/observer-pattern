"""Core types for eventforge message queue and execution."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from eventforge.executor import Executor


class TaskStatus(str, Enum):
    """Task execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Message(BaseModel):
    """Message for pub-sub communication."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    topic: str
    payload: Any
    headers: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reply_to: str | None = None
    correlation_id: str | None = None

    model_config = {"arbitrary_types_allowed": True}


class TaskRequest(BaseModel):
    """Request to execute a task."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    func_name: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    timeout: float | None = None

    @field_validator("args", mode="before")
    @classmethod
    def convert_args(cls, v):
        if isinstance(v, list):
            return tuple(v)
        return v


class TaskResult(BaseModel):
    """Result of task execution."""

    task_id: str
    status: TaskStatus
    value: Any = None
    error: str | None = None
    error_type: str | None = None
    execution_time: float = 0.0
    worker_id: str = ""

    model_config = {"arbitrary_types_allowed": True}

    @property
    def is_success(self) -> bool:
        return self.status == TaskStatus.COMPLETED

    @property
    def is_failure(self) -> bool:
        return self.status == TaskStatus.FAILED


class RPCRequest(BaseModel):
    """RPC method call request."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    method: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = Field(default_factory=dict)
    timeout: float | None = None

    @field_validator("args", mode="before")
    @classmethod
    def convert_args(cls, v):
        if isinstance(v, list):
            return tuple(v)
        return v


class RPCResponse(BaseModel):
    """RPC method call response."""

    id: str
    request_id: str
    result: Any = None
    error: str | None = None
    error_type: str | None = None

    model_config = {"arbitrary_types_allowed": True}

    @property
    def is_success(self) -> bool:
        return self.error is None


class Subscription(BaseModel):
    """Subscription to a topic."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    topic: str
    pattern: bool = False  # True if topic is a pattern (e.g., "user.*")


class SharedState:
    """Thread-safe shared state for observers and tasks.

    Provides atomic operations for sharing data across task invocations
    and between observers. Each task has its own SharedState instance.

    Example:
        state = SharedState()

        # Simple get/set
        state.set("count", 0)
        state.get("count")  # 0

        # Atomic update
        state.update("count", lambda x: (x or 0) + 1)  # Returns 1
        state.update("count", lambda x: (x or 0) + 1)  # Returns 2

        # Get all data
        state.items()  # {"count": 2}
    """

    def __init__(self):
        self._data: dict[str, Any] = {}
        self._lock = threading.RLock()

    def get(self, key: str, default: Any = None) -> Any:
        """Get value by key."""
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set value by key."""
        with self._lock:
            self._data[key] = value

    def update(self, key: str, func: Callable[[Any], Any]) -> Any:
        """Atomically update a value using a function.

        Args:
            key: Key to update
            func: Function that takes old value and returns new value

        Returns:
            The new value after update

        Example:
            state.update("count", lambda x: (x or 0) + 1)
        """
        with self._lock:
            old = self._data.get(key)
            new = func(old)
            self._data[key] = new
            return new

    def delete(self, key: str) -> bool:
        """Delete a key. Returns True if key existed."""
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all data."""
        with self._lock:
            self._data.clear()

    def items(self) -> dict[str, Any]:
        """Get a copy of all items."""
        with self._lock:
            return self._data.copy()

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._data


@dataclass
class TaskContext:
    """Context passed through entire task lifecycle.

    This enhanced context provides:
    - Task identification (task_id, func_name, topic)
    - Execution info (args, kwargs, executor reference)
    - Timing (start_time, end_time, execution_time property)
    - Result/error storage
    - Shared state for observers
    - Metadata dict for custom data

    Example:
        ctx = TaskContext(
            task_id="abc123",
            func_name="process_data",
            args=("hello",),
            kwargs={},
            state=SharedState(),
        )

        # After execution
        ctx.result = "HELLO"
        ctx.end_time = time.time()
        print(ctx.execution_time)  # 0.001
        print(ctx.is_success)  # True
    """

    # Task identification
    task_id: str
    func_name: str
    topic: str | None = None

    # Execution info
    args: tuple = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    executor: Optional["Executor"] = None

    # Timing
    start_time: float = 0.0
    end_time: float = 0.0

    # Result
    result: Any = None
    error: Exception | None = None

    # Shared state (thread-safe, shared across invocations)
    state: SharedState | None = None

    # Metadata (per-invocation)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def execution_time(self) -> float:
        """Execution time in seconds."""
        return self.end_time - self.start_time

    @property
    def is_success(self) -> bool:
        """True if no error occurred."""
        return self.error is None

    @property
    def is_failure(self) -> bool:
        """True if an error occurred."""
        return self.error is not None
