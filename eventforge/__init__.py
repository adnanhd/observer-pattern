"""eventforge: observer pattern + pub-sub + RPC + work queue, one package.

A unified ``Observable`` + ``Eventful`` + ``Dispatcher`` primitive
covers in-process pub-sub, cross-process RPC, work queues, parallel
fan-out, and resource-aware load balancing. Meters measure tasks and
emit events; Reporters subscribe to Meter emissions and ship them
externally (logging, syslog, OpenTelemetry, ...).
"""

from eventforge.caller import Caller
from eventforge.executor import ExecutionMode, Executor, LocalProcedureCaller
from eventforge.observers import (
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
from eventforge.queue import MessageQueue
from eventforge.remote import RemoteQueue, RemoteSubscription
from eventforge.rpc import RoundRobinRPCClient, RPCClient, RPCServer, with_retry
from eventforge.task import TaskPool, TaskRunner, task
from eventforge.transports import (
    MemoryTransport,
    TCPClientTransport,
    TCPServerTransport,
    Transport,
)
from eventforge.types import (
    Message,
    RPCRequest,
    RPCResponse,
    SharedState,
    TaskContext,
    TaskRequest,
    TaskResult,
    TaskStatus,
)
from eventforge.work_queue import QueueFullError, WorkQueue

__version__ = "0.1.0"
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
    # Executor / Caller
    "LocalProcedureCaller",
    "Caller",
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
