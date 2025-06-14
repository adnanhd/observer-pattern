"""
CallPyBack: Advanced callback decorator with formal design patterns.

This package provides a theoretically sound implementation of the observer pattern
for Python function decoration, addressing common limitations in callback systems.
"""

from callpyback.core.context import ExecutionContext, ExecutionFailure, ExecutionResult
from callpyback.core.decorator import CallPyBack
from callpyback.core.state_machine import ExecutionPhase, ExecutionState
from callpyback.errors import CallPyBackError, ObserverError, StateTransitionError
from callpyback.factories import (
    create_callback_observer,
    on_call,
    on_completion,
    on_failure,
    on_success,
)
from callpyback.observers.base import BaseObserver
from callpyback.observers.builtin import (
    LoggingObserver,
    MetricsObserver,
    TimingObserver,
)
from callpyback.observers.callback import CallbackObserver

from callpyback.management.error_handling import (
    DefaultErrorHandler,
    ConditionalErrorHandler,
)

__version__ = "2.0.0"
__author__ = "Adnan Harun Dogan"
__email__ = "adnanharundogan@gmail.com"

__all__ = [
    # Core classes
    "CallPyBack",
    "ExecutionContext",
    "ExecutionResult",
    "ExecutionFailure",
    "ExecutionState",
    "ExecutionPhase",
    # Observer classes
    "BaseObserver",
    "CallbackObserver",
    "LoggingObserver",
    "MetricsObserver",
    "TimingObserver",
    # Factory functions
    "on_call",
    "on_success",
    "on_failure",
    "on_completion",
    "create_callback_observer",
    # Exceptions
    "CallPyBackError",
    "StateTransitionError",
    "ObserverError",
    # Error handling
    "DefaultErrorHandler",
    "ConditionalErrorHandler",
]
