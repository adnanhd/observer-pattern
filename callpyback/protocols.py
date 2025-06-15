"""Protocol definitions for CallPyBack interfaces."""

from typing_compat import (
    Any,
    ContextManager,
    Dict,
    List,
    Protocol,
    runtime_checkable,
)

from callpyback.core.context import ExecutionContext


@runtime_checkable
class Observer(Protocol):
    """Protocol for observer objects."""

    def update(self, context: ExecutionContext) -> None:
        """Handle execution context update."""
        ...

    @property
    def priority(self) -> int:
        """Observer execution priority (higher = earlier)."""
        ...


@runtime_checkable
class VariableExtractor(Protocol):
    """Protocol for variable extraction strategies."""

    def setup_extraction(self) -> ContextManager[None]:
        """Set up variable extraction context."""
        ...

    def extract_variables(self, variable_names: List[str]) -> Dict[str, Any]:
        """Extract requested variables."""
        ...


@runtime_checkable
class TimeSource(Protocol):
    """Protocol for time sources (enables testing)."""

    def now(self) -> float:
        """Get current timestamp."""
        ...


@runtime_checkable
class ObserverManager(Protocol):
    """Protocol for observer management."""

    def add_observer(self, observer: Observer) -> None:
        """Add observer to the system."""
        ...

    def remove_observer(self, observer: Observer) -> None:
        """Remove observer from the system."""
        ...

    def notify_observers(self, context: ExecutionContext) -> None:
        """Notify all relevant observers."""
        ...


@runtime_checkable
class ErrorHandler(Protocol):
    """Protocol for error handling strategies."""

    def handle_error(self, error: Exception, context: ExecutionContext) -> Any:
        """Handle execution error."""
        ...
