"""
CallPyBack Plugins - Event-driven, Pub-Sub, and Distributed Extensions

This package extends CallPyBack with:
- Event-driven messaging patterns
- Publish-subscribe systems
- Multi-threaded/multi-process execution
- REST API integration
- Inter-process communication
- Task scheduling and distribution
"""

from callpyback.plugins.core.event_bus import EventBus
from callpyback.plugins.core.message_queue import MessageQueue
from callpyback.plugins.core.topic_registry import TopicRegistry
from callpyback.plugins.executors.hybrid_executor import HybridExecutor
from callpyback.plugins.executors.process_executor import ProcessExecutor
from callpyback.plugins.executors.thread_executor import ThreadExecutor
from callpyback.plugins.manager import (
    CallPyBackPluginManager,
    EventPriority,
    ExecutionMode,
    PluginConfig,
    emit_event,
    get_manager,
    on_event,
    plugin_session,
    run_parallel,
)

__version__ = "1.0.1"
__author__ = "Adnan Harun Doğan"

__all__ = [
    # v1.0.0
    "MessageQueue",
    "EventBus",
    "TopicRegistry",
    "ThreadExecutor",
    "ProcessExecutor",
    "HybridExecutor",
    # v1.0.1
    "CallPyBackPluginManager",
    "PluginConfig",
    "ExecutionMode",
    "EventPriority",
    "get_manager",
    "plugin_session",
    "run_parallel",
    "emit_event",
    "on_event",
]
