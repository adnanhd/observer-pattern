"""
CallPyBack: Message-driven function pipelines with pub-sub, executors, and RPC.

This package provides a clean implementation of message queues, pipelines,
and remote procedure calls for Python function orchestration.
"""

from callpyback.executor import ExecutionMode, Executor
from callpyback.observers import (
    CallbackObserver,
    CompositeObserver,
    ExecutionContext,
    FLOPsObserver,
    MemoryObserver,
    MetricsObserver,
    Observer,
    TimingObserver,
    observe,
)
from callpyback.pipeline import Pipeline, PipelineStep, task
from callpyback.queue import MessageQueue
from callpyback.rpc import RPCClient, RPCServer
from callpyback.transports import MemoryTransport, Transport
from callpyback.types import (
    Message,
    RPCRequest,
    RPCResponse,
    TaskRequest,
    TaskResult,
    TaskStatus,
)

__version__ = "3.0.0"
__author__ = "Adnan Harun Dogan"
__email__ = "adnanharundogan@gmail.com"

__all__ = [
    # Types
    "Message",
    "TaskRequest",
    "TaskResult",
    "TaskStatus",
    "RPCRequest",
    "RPCResponse",
    # Transport
    "Transport",
    "MemoryTransport",
    # Queue
    "MessageQueue",
    # Executor
    "Executor",
    "ExecutionMode",
    # Pipeline
    "Pipeline",
    "PipelineStep",
    "task",
    # RPC
    "RPCServer",
    "RPCClient",
    # Observers
    "Observer",
    "ExecutionContext",
    "TimingObserver",
    "MetricsObserver",
    "MemoryObserver",
    "FLOPsObserver",
    "CompositeObserver",
    "CallbackObserver",
    "observe",
]
