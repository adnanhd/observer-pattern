"""Core types for CallPyBack message queue and execution."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


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
    headers: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reply_to: Optional[str] = None
    correlation_id: Optional[str] = None

    model_config = {"arbitrary_types_allowed": True}


class TaskRequest(BaseModel):
    """Request to execute a task."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    func_name: str
    args: Tuple[Any, ...] = ()
    kwargs: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    timeout: Optional[float] = None

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
    error: Optional[str] = None
    error_type: Optional[str] = None
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
    args: Tuple[Any, ...] = ()
    kwargs: Dict[str, Any] = Field(default_factory=dict)
    timeout: Optional[float] = None

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
    error: Optional[str] = None
    error_type: Optional[str] = None

    model_config = {"arbitrary_types_allowed": True}

    @property
    def is_success(self) -> bool:
        return self.error is None


class Subscription(BaseModel):
    """Subscription to a topic."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    topic: str
    pattern: bool = False  # True if topic is a pattern (e.g., "user.*")
