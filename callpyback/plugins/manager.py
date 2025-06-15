#!/usr/bin/env python3
"""
CallPyBack Plugin Manager - Unified interface for all plugins.
"""

import threading
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar, Union

from callpyback.plugins.config import (
    ConfigBuilder,
    EventPriority,
    ExecutionMode,
    PluginConfig,
)
from callpyback.plugins.core.event_bus import EventBus
from callpyback.plugins.core.message_queue import MessageQueue
from callpyback.plugins.core.topic_registry import TopicRegistry
from callpyback.plugins.executors.hybrid_executor import HybridExecutor
from callpyback.plugins.executors.process_executor import ProcessExecutor
from callpyback.plugins.executors.thread_executor import ThreadExecutor

T = TypeVar("T")

Executor = Union[HybridExecutor, ProcessExecutor, ThreadExecutor]


class CallPyBackPluginManager:
    """Unified interface for all CallPyBack plugins."""

    def __init__(self, config: Optional[PluginConfig] = None):
        self.config = config or PluginConfig()

        self.event_bus: Optional[EventBus] = None
        self.message_queue: Optional[MessageQueue] = None
        self.topic_registry: Optional[TopicRegistry] = None
        self.executor: Optional[Executor] = None

        self._started = False
        self._lock = threading.RLock()
        self._metrics = {
            "tasks_submitted": 0,
            "tasks_completed": 0,
            "events_published": 0,
            "errors": 0,
        }

        if self.config.auto_start_services:
            self._initialize_plugins()

    def _initialize_plugins(self):
        """Initialize enabled plugins."""
        with self._lock:
            if self._started:
                return

            if self.config.enable_events:
                self.event_bus = EventBus()

            if self.config.enable_message_queue:
                self.message_queue = MessageQueue()

            if self.config.enable_topics:
                self.topic_registry = TopicRegistry()

            if (
                self.config.enable_hybrid
                and self.config.max_threads
                and self.config.max_processes
            ):
                self.executor = HybridExecutor(
                    max_threads=self.config.max_threads,
                    max_processes=self.config.max_processes,
                )

            elif self.config.max_threads:
                self.executor = ThreadExecutor(max_workers=self.config.max_threads)

            elif self.config.max_processes:
                self.executor = ProcessExecutor(max_workers=self.config.max_processes)

    def start(self):
        """Start all services."""
        with self._lock:
            if self._started:
                return

            self._initialize_plugins()

            if self.executor:
                self.executor.start()

            if self.message_queue:
                self.message_queue.start()

            self._started = True

    def is_running(self) -> bool:
        return self._started

    def stop(self, wait: bool = True, timeout: float = 30.0):
        """Stop all services."""
        with self._lock:
            if not self._started:
                return

            if self.executor:
                self.executor.stop(wait=wait, timeout=timeout)

            if self.message_queue:
                self.message_queue.stop()

            self._started = False

    def get_executor_mode(self) -> Optional[ExecutionMode]:
        if isinstance(self.executor, ThreadExecutor):
            return ExecutionMode.THREAD
        elif isinstance(self.executor, ProcessExecutor):
            return ExecutionMode.PROCESS
        elif isinstance(self.executor, HybridExecutor):
            return ExecutionMode.HYBRID
        else:
            return None

    def run(
        self, func: Callable, *args, mode: Optional[ExecutionMode] = None, **kwargs
    ) -> Any:
        """Run function with specified execution mode."""
        mode = mode or self.config.default_execution_mode

        if mode == ExecutionMode.SYNC:
            return func(*args, **kwargs)

        if self.executor is None:
            raise ValueError(f"Executor is not initialized for mode {mode}")
        else:
            task_id = self.executor.submit(func, *args, **kwargs)
            result = self.executor.get_result(task_id, timeout=30)
            return result.result

    def async_run(
        self, func: Callable, *args, mode: Optional[ExecutionMode] = None, **kwargs
    ) -> str:
        """Submit function for async execution."""
        mode = mode or self.config.default_execution_mode
        self._metrics["tasks_submitted"] += 1

        if self.executor is None:
            raise ValueError(f"Executor not initialized for mode: {mode}")
        else:
            return self.executor.submit(func, *args, **kwargs)

    def parallel(
        self,
        *functions: Union[Callable, Tuple[Callable, Any]],
        mode: Optional[ExecutionMode] = None,
    ) -> List[Any]:
        """Execute functions in parallel."""
        mode = mode or self.config.default_execution_mode

        task_ids = []
        for func in functions:
            if callable(func):
                task_id = self.async_run(func, mode=mode)
                task_ids.append(task_id)
            else:
                func_call, *args = func
                task_id = self.async_run(func_call, *args, mode=mode)
                task_ids.append(task_id)

        results = []
        for task_id in task_ids:
            try:
                if self.executor:
                    result = self.executor.get_result(task_id, timeout=30)
                else:
                    raise ValueError(f"Executor not initialized for mode: {mode}")

                results.append(result.result if hasattr(result, "result") else result)
                self._metrics["tasks_completed"] += 1
            except Exception as e:
                results.append(e)
                self._metrics["errors"] += 1

        return results

    def map_parallel(
        self, func: Callable, items: List[Any], mode: Optional[ExecutionMode] = None
    ) -> List[Any]:
        """Map function over items in parallel."""
        mode = mode or self.config.default_execution_mode
        func_calls = [(func, item) for item in items]
        return self.parallel(*func_calls, mode=mode)

    def on(
        self,
        topic_pattern: str,
        priority: Optional[EventPriority] = None,
        once: bool = False,
    ):
        """Decorator for event handlers."""
        priority = priority or self.config.default_event_priority

        def decorator(func: Callable) -> Callable:
            if self.event_bus:
                if hasattr(self.event_bus, "on"):
                    if once:
                        handler = self.event_bus.on(
                            topic_pattern, priority=priority.value, max_calls=1
                        )
                    else:
                        handler = self.event_bus.on(
                            topic_pattern, priority=priority.value
                        )
                    handler(func)
                else:
                    self.event_bus.subscribe(topic_pattern, func)
            return func

        return decorator

    def once(self, topic_pattern: str, priority: Optional[EventPriority] = None):
        """Decorator for one-time event handlers."""
        return self.on(topic_pattern, priority, once=True)

    def emit(self, topic: str, data: Any = None, **headers) -> str:
        """Emit event with data."""
        if not self.event_bus:
            raise RuntimeError("Event bus not initialized")

        self._metrics["events_published"] += 1
        return self.event_bus.publish(topic, data, headers=headers)

    def request(self, topic: str, data: Any = None, timeout: float = 10.0) -> Any:
        """Request-response pattern."""
        if not self.event_bus or not hasattr(self.event_bus, "request_response"):
            raise RuntimeError(
                "Event bus not initialized or doesn't support request-response"
            )
        return self.event_bus.request_response(topic, data, timeout=timeout)

    def create_topic(
        self, name: str, description: str = "", schema: Optional[Dict] = None, **tags
    ):
        """Create and register a topic."""
        if not self.topic_registry:
            raise RuntimeError("Topic registry not initialized")
        return self.topic_registry.register_topic(
            name=name,
            description=description,
            schema=schema,
            tags=set(tags.keys()) if tags else set(),
        )

    def configure(self) -> "ConfigBuilder":
        """Get fluent configuration builder."""
        return ConfigBuilder(self)

    @contextmanager
    def session(self):
        """Context manager for automatic start/stop."""
        self.start()
        try:
            yield self
        finally:
            self.stop()

    def get_metrics(self) -> Dict[str, Any]:
        """Get comprehensive metrics from all plugins."""
        metrics: Dict[str, Any] = dict(self._metrics)
        if self.executor and hasattr(self.executor, "get_stats"):
            metrics["executor"] = self.executor.get_stats()
        if self.event_bus and hasattr(self.event_bus, "get_stats"):
            metrics["event_bus"] = self.event_bus.get_stats()
        if self.topic_registry and hasattr(self.topic_registry, "get_stats"):
            metrics["topic_registry"] = self.topic_registry.get_stats()

        return metrics

    def health_check(self) -> Dict[str, str]:
        """Check health of all services."""
        health = {"plugin_manager": "healthy" if self._started else "stopped"}

        if isinstance(self.executor, (ThreadExecutor, ProcessExecutor)):
            health["executor"] = "healthy" if self.executor.running else "stopped"
        elif isinstance(self.executor, HybridExecutor):
            health["executor"] = "healthy"

        if self.event_bus:
            health["event_bus"] = "healthy" if self.event_bus.running else "stopped"

        return health


_global_manager: Optional[CallPyBackPluginManager] = None


def get_manager() -> CallPyBackPluginManager:
    """Get global plugin manager instance."""
    global _global_manager
    if _global_manager is None:
        _global_manager = CallPyBackPluginManager()
    if not _global_manager.is_running():
        _global_manager.start()
    return _global_manager


def run_parallel(*functions, mode: Optional[ExecutionMode] = None) -> List[Any]:
    """Global parallel execution."""
    return get_manager().parallel(*functions, mode=mode)


def emit_event(topic: str, data: Any = None, **headers) -> str:
    """Global event emission."""
    return get_manager().emit(topic, data, **headers)


def on_event(
    topic_pattern: str, priority: Optional[EventPriority] = None, once: bool = False
):
    """Global event handler decorator."""
    return get_manager().on(topic_pattern, priority, once)


@contextmanager
def plugin_session(config: Optional[PluginConfig] = None):
    """Global context manager for plugin usage."""
    if config:
        manager = CallPyBackPluginManager(config)
    else:
        manager = get_manager()

    with manager.session():
        yield manager
