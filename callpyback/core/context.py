"""Execution context and result objects."""

import inspect
import time
from dataclasses import dataclass, field

from typing_compat import Any, Callable, Dict, Optional, Union

from callpyback.core.state_machine import ExecutionState


@dataclass(frozen=True)
class FunctionSignature:
    """Immutable representation of function metadata."""

    name: str
    module: str
    parameters: tuple
    annotations: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_callable(cls, func: Callable) -> "FunctionSignature":
        """Create signature from callable."""
        sig = inspect.signature(func)
        return cls(
            name=func.__name__,
            module=getattr(func, "__module__", "<unknown>"),
            parameters=tuple(sig.parameters.keys()),
            annotations=getattr(func, "__annotations__", {}),
        )


@dataclass(frozen=True)
class ExecutionResult:
    """Immutable execution result for successful executions."""

    value: Any
    execution_time: float
    memory_usage: Optional[int] = None

    @property
    def is_success(self) -> bool:
        return True


@dataclass(frozen=True)
class ExecutionFailure:
    """Immutable execution result for failed executions."""

    exception: Exception
    exception_type: type
    traceback_info: str
    execution_time: float

    @property
    def is_success(self) -> bool:
        return False


@dataclass(frozen=True)
class ExecutionContext:
    """Immutable aggregate root for execution context."""

    function_signature: FunctionSignature
    arguments: Dict[str, Any]
    state: ExecutionState
    result: Optional[Union[ExecutionResult, ExecutionFailure]] = None
    local_variables: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def is_successful(self) -> bool:
        """Check if execution was successful."""
        return isinstance(self.result, ExecutionResult)

    @property
    def is_failed(self) -> bool:
        """Check if execution failed."""
        return isinstance(self.result, ExecutionFailure)

    def with_state(self, new_state: ExecutionState) -> "ExecutionContext":
        """Create new context with updated state."""
        # Use dataclasses.replace for Python 3.8 compatibility
        from dataclasses import replace

        return replace(self, state=new_state)

    def with_result(
        self, result: Union[ExecutionResult, ExecutionFailure]
    ) -> "ExecutionContext":
        """Create new context with result."""
        from dataclasses import replace

        return replace(self, result=result)

    def with_variables(self, variables: Dict[str, Any]) -> "ExecutionContext":
        """Create new context with local variables."""
        from dataclasses import replace

        return replace(self, local_variables=variables)
