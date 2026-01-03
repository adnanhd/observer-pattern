#!/usr/bin/env python3
"""
Plugin Manager - Conceptual Example
Demonstrates extensible plugin architecture using observers and message queue.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from callpyback import (
    ExecutionContext,
    MessageQueue,
    Observer,
    TimingObserver,
    observe,
)


class Plugin(ABC):
    """Base plugin interface."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def initialize(self, queue: MessageQueue) -> None:
        pass

    @abstractmethod
    def shutdown(self) -> None:
        pass


class PluginObserver(Observer):
    """Observer that notifies plugins of execution events."""

    def __init__(self, queue: MessageQueue):
        self.queue = queue

    def on_start(self, ctx: ExecutionContext) -> None:
        self.queue.publish(
            "plugin.execution.start",
            {"func_name": ctx.func_name, "args": str(ctx.args)},
        )

    def on_end(self, ctx: ExecutionContext) -> None:
        self.queue.publish(
            "plugin.execution.end",
            {
                "func_name": ctx.func_name,
                "success": ctx.is_success,
                "execution_time": ctx.execution_time,
            },
        )


class LoggingPlugin(Plugin):
    """Plugin that logs all events."""

    @property
    def name(self) -> str:
        return "logging"

    def initialize(self, queue: MessageQueue) -> None:
        self.queue = queue

        @queue.on("plugin.execution.start")
        def on_start(msg):
            print(f"[LOG] Starting: {msg.payload['func_name']}")

        @queue.on("plugin.execution.end")
        def on_end(msg):
            status = "OK" if msg.payload["success"] else "FAILED"
            print(f"[LOG] Finished: {msg.payload['func_name']} [{status}]")

    def shutdown(self) -> None:
        print("[LOG] Logging plugin shutdown")


class MetricsPlugin(Plugin):
    """Plugin that collects metrics."""

    def __init__(self):
        self.call_counts: Dict[str, int] = {}
        self.total_time: Dict[str, float] = {}

    @property
    def name(self) -> str:
        return "metrics"

    def initialize(self, queue: MessageQueue) -> None:
        self.queue = queue

        @queue.on("plugin.execution.end")
        def on_end(msg):
            func_name = msg.payload["func_name"]
            exec_time = msg.payload["execution_time"]

            self.call_counts[func_name] = self.call_counts.get(func_name, 0) + 1
            self.total_time[func_name] = self.total_time.get(func_name, 0) + exec_time

    def shutdown(self) -> None:
        print(f"[METRICS] Call counts: {self.call_counts}")
        print(f"[METRICS] Total time: {self.total_time}")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "call_counts": self.call_counts.copy(),
            "total_time": self.total_time.copy(),
        }


class PluginManager:
    """Manages plugin lifecycle."""

    def __init__(self):
        self.queue = MessageQueue()
        self.plugins: List[Plugin] = []
        self.observer = PluginObserver(self.queue)

    def register(self, plugin: Plugin) -> None:
        plugin.initialize(self.queue)
        self.plugins.append(plugin)
        print(f"Registered plugin: {plugin.name}")

    def shutdown(self) -> None:
        for plugin in self.plugins:
            plugin.shutdown()
        self.queue.close()

    def get_observer(self) -> Observer:
        return self.observer


def main():
    # Create plugin manager
    manager = PluginManager()

    # Register plugins
    logging_plugin = LoggingPlugin()
    metrics_plugin = MetricsPlugin()

    manager.register(logging_plugin)
    manager.register(metrics_plugin)

    # Create functions with plugin observer
    timing = TimingObserver()

    @observe(manager.get_observer(), timing)
    def process_data(data: str) -> str:
        return data.upper()

    @observe(manager.get_observer(), timing)
    def calculate(x: int, y: int) -> int:
        return x + y

    # Execute functions
    print("\n=== Executing Functions ===")
    process_data("hello")
    process_data("world")
    calculate(1, 2)
    calculate(3, 4)
    calculate(5, 6)

    # Show metrics
    print("\n=== Plugin Stats ===")
    print(f"Timing: {timing.stats}")

    # Shutdown
    print("\n=== Shutdown ===")
    manager.shutdown()


if __name__ == "__main__":
    main()
