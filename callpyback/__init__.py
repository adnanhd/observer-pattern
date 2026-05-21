"""CallPyBack: event-driven task execution with pluggable dispatch.

Unified primitive (``Observable`` + ``Eventful`` + ``Dispatcher``) covers
in-process pub-sub, cross-process RPC, work queues, parallel fanout, and
resource-aware load balancing. Meters measure tasks and emit events;
Reporters subscribe to Meter emissions and ship them externally.
"""

from callpyback.executor import ExecutionMode, Executor
from callpyback.observers import (
    BroadcastDispatcher,
    ConcurrentDispatcher,
    CPUMeter,
    Dispatcher,
    Eventful,
    ExecutionContext,
    LeastLoadedDispatcher,
    LoggingReporter,
    MemoryMeter,
    Meter,
    MetricsMeter,
    Node,
    Observable,
    Reporter,
    RoundRobinDispatcher,
    TimingMeter,
    observe,
)
from callpyback.queue import MessageQueue
from callpyback.remote import RemoteQueue, RemoteSubscription
from callpyback.rpc import RoundRobinRPCClient, RPCClient, RPCServer, with_retry
from callpyback.task import TaskPool, TaskRunner, task
from callpyback.transports import (
    MemoryTransport,
    TCPClientTransport,
    TCPServerTransport,
    Transport,
)
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
from callpyback.work_queue import QueueFullError, WorkQueue

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
    "ExecutionContext",
    # Transport
    "Transport",
    "MemoryTransport",
    "TCPServerTransport",
    "TCPClientTransport",
    # Queue
    "MessageQueue",
    "RemoteQueue",
    "RemoteSubscription",
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
    # Observability core
    "Observable",
    "Eventful",
    "Dispatcher",
    "Node",
    "observe",
    # Dispatchers
    "BroadcastDispatcher",
    "RoundRobinDispatcher",
    "ConcurrentDispatcher",
    "LeastLoadedDispatcher",
    # Meters
    "Meter",
    "TimingMeter",
    "MemoryMeter",
    "CPUMeter",
    "MetricsMeter",
    # Reporters
    "Reporter",
    "LoggingReporter",
]
