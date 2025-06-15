from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol


class ExecutionMode(Enum):
    SYNC = "sync"
    THREAD = "thread"
    PROCESS = "process"
    HYBRID = "hybrid"


class EventPriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class PluginConfig:
    """Configuration for plugin manager."""

    max_threads: int = 4
    max_processes: Optional[int] = None
    enable_hybrid: bool = True
    enable_events: bool = True
    enable_topics: bool = True
    enable_message_queue: bool = True
    default_execution_mode: ExecutionMode = ExecutionMode.HYBRID
    default_event_priority: EventPriority = EventPriority.NORMAL
    auto_start_services: bool = True
    enable_monitoring: bool = True


class PluginManager(Protocol):
    """Protocol for plugin manager."""

    config: PluginConfig

    def is_running(self) -> bool: ...
    def start(self) -> None: ...


class ConfigBuilder:
    """Fluent configuration builder."""

    def __init__(self, manager: PluginManager):
        self.manager = manager
        self.config = manager.config

    def max_threads(self, max_workers: int) -> "ConfigBuilder":
        """Configure thread executor."""
        self.config.max_threads = max_workers
        return self

    def max_processes(self, max_workers: int) -> "ConfigBuilder":
        """Configure process executor."""
        self.config.max_processes = max_workers
        return self

    def enable_hybrid(self, enabled: bool = True) -> "ConfigBuilder":
        """Enable/disable hybrid executor."""
        self.config.enable_hybrid = enabled
        return self

    def enable_events(self, enabled: bool = True) -> "ConfigBuilder":
        """Enable/disable event executor."""
        self.config.enable_events = enabled
        return self

    def enable_topics(self, enabled: bool = True) -> "ConfigBuilder":
        """Enable/disable topic executor."""
        self.config.enable_topics = enabled
        return self

    def enable_message_queue(self, enabled: bool = True) -> "ConfigBuilder":
        """Enable/disable message queue executor."""
        self.config.enable_message_queue = enabled
        return self

    def execution_mode(self, mode: ExecutionMode) -> "ConfigBuilder":
        """Set default execution mode."""
        self.config.default_execution_mode = mode
        return self

    def event_priority(self, priority: EventPriority) -> "ConfigBuilder":
        """Set default event priority."""
        self.config.default_event_priority = priority
        return self

    def auto_start(self, enabled: bool = True) -> "ConfigBuilder":
        """Enable/disable auto-start."""
        self.config.auto_start_services = enabled
        return self

    def enable_monitoring(self, enabled: bool = True) -> "ConfigBuilder":
        """Enable/disable monitoring."""
        self.config.enable_monitoring = enabled
        return self

    def apply(self) -> PluginManager:
        """Apply configuration and return manager."""
        if self.config.auto_start_services and not self.manager.is_running():
            self.manager.start()
        return self.manager
