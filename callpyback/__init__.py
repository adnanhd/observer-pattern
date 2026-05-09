"""
CallPyBack: Message-driven task execution with pub-sub, executors, and RPC.

This package provides a unified task execution system combining message queues,
executors, observers, and remote procedure calls for Python function orchestration.
"""

from callpyback.executor import ExecutionMode, Executor
from callpyback.observers import (
    CallbackObserver,
    CompositeObserver,
    CPUObserver,
    ExecutionContext,
    LoggingObserver,
    MemoryObserver,
    Meter,
    MeterObserver,
    MetricsObserver,
    Observer,
    TimingObserver,
    observe,
)
from callpyback.queue import MessageQueue
from callpyback.work_queue import QueueFullError, WorkQueue
from callpyback.remote import RemoteQueue, RemoteSubscription
from callpyback.rpc import RoundRobinRPCClient, RPCClient, RPCServer, with_retry
from callpyback.task import TaskPool, TaskRunner, task
from callpyback.transports import MemoryTransport, Transport, TCPServerTransport, TCPClientTransport
from callpyback.types import (
    Message,
    RPCRequest,
    RPCResponse,
    SharedState,
    TaskContext,
    TaskRequest,
    TaskResult,
    TaskStatus,
)

__version__ = "4.0.0"
__author__ = "Adnan Harun Dogan"
__email__ = "adnanharundogan@gmail.com"

__all__ = [
    # Types
    "Message",
    "TaskRequest",
    "TaskResult",
    "TaskStatus",
    "TaskContext",
    "SharedState",
    "RPCRequest",
    "RPCResponse",
    # Transport
    "Transport",
    "MemoryTransport",
    "TCPServerTransport",
    "TCPClientTransport",
    # Queue
    "MessageQueue",
    "RemoteQueue",
    "RemoteSubscription",
    # Work Queue
    "WorkQueue",
    "QueueFullError",
    # Executor
    "Executor",
    "ExecutionMode",
    # Task
    "task",
    "TaskRunner",
    "TaskPool",
    # RPC
    "RPCServer",
    "RPCClient",
    "RoundRobinRPCClient",
    "with_retry",
    # Observers
    "Observer",
    "ExecutionContext",
    "TimingObserver",
    "MetricsObserver",
    "LoggingObserver",
    "MemoryObserver",
    "CPUObserver",
    "CompositeObserver",
    "CallbackObserver",
    "observe",
    # Meters
    "Meter",
    "MeterObserver",
]
