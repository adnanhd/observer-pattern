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

from callpyback.plugins.core.message_queue import MessageQueue, EventBus
from callpyback.plugins.core.topic_registry import TopicRegistry
from callpyback.plugins.executors.thread_executor import ThreadExecutor
from callpyback.plugins.executors.process_executor import ProcessExecutor
from callpyback.plugins.executors.hybrid_executor import HybridExecutor

__version__ = "1.0.0"
__author__ = "CallPyBack Contributors"

__all__ = [
    "MessageQueue",
    "EventBus",
    "TopicRegistry",
    "ThreadExecutor",
    "ProcessExecutor",
    "HybridExecutor",
]
