"""Exception classes for CallPyBack."""

from typing_compat import List


class CallPyBackError(Exception):
    """Base exception for all CallPyBack errors."""


class StateTransitionError(CallPyBackError):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, from_state: str, to_state: str, valid_transitions: List[str]):
        self.from_state = from_state
        self.to_state = to_state
        self.valid_transitions = valid_transitions
        super().__init__(
            f"Invalid transition from {from_state} to {to_state}. "
            f"Valid transitions: {valid_transitions}"
        )


class ObserverError(CallPyBackError):
    """Raised when observer operations fail."""


class ConfigurationError(CallPyBackError):
    """Raised when CallPyBack is misconfigured."""


class ExecutionError(CallPyBackError):
    """Raised when function execution fails in unexpected ways."""
