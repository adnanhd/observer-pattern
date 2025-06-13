"""Factory functions for creating common observers."""

from typing_compat import Callable, Optional, Set

from callpyback.core.state_machine import ExecutionPhase, ExecutionState
from callpyback.observers.callback import CallbackObserver


def create_callback_observer(
    callback: Callable,
    states: Optional[Set[ExecutionState]] = None,
    phases: Optional[Set[ExecutionPhase]] = None,
    priority: int = 0,
    name: Optional[str] = None,
) -> CallbackObserver:
    """Create a callback observer with specified configuration."""
    return CallbackObserver(
        callback=callback,
        interested_states=states or {ExecutionState.COMPLETED},
        priority=priority,
        name=name,
    )


def on_call(
    callback: Callable, priority: int = 0, name: Optional[str] = None
) -> CallbackObserver:
    """Create observer for before-call phase."""
    return create_callback_observer(
        callback=callback,
        states={ExecutionState.PRE_EXECUTION},
        priority=priority,
        name=name or "OnCall",
    )


def on_success(
    callback: Callable, priority: int = 0, name: Optional[str] = None
) -> CallbackObserver:
    """Create observer for success phase."""
    return create_callback_observer(
        callback=callback,
        states={ExecutionState.POST_SUCCESS},
        priority=priority,
        name=name or "OnSuccess",
    )


def on_failure(
    callback: Callable, priority: int = 0, name: Optional[str] = None
) -> CallbackObserver:
    """Create observer for failure phase."""
    return create_callback_observer(
        callback=callback,
        states={ExecutionState.POST_FAILURE},
        priority=priority,
        name=name or "OnFailure",
    )


def on_completion(
    callback: Callable, priority: int = 0, name: Optional[str] = None
) -> CallbackObserver:
    """Create observer for completion phase."""
    return create_callback_observer(
        callback=callback,
        states={ExecutionState.COMPLETED},
        priority=priority,
        name=name or "OnCompletion",
    )
