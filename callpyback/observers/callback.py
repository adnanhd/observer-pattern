"""Callback observer implementation."""

import inspect
import logging

from typing_compat import Any, Callable, Dict, Optional, Set

from callpyback.core.context import ExecutionContext
from callpyback.core.state_machine import ExecutionState
from callpyback.errors import ConfigurationError
from callpyback.observers.base import BaseObserver


class CallbackObserver(BaseObserver):
    """Observer that wraps callback functions."""

    def __init__(
        self,
        callback: Callable,
        interested_states: Optional[Set[ExecutionState]] = None,
        priority: int = 0,
        name: Optional[str] = None,
    ):
        super().__init__(priority, name)
        self._callback = callback
        self._interested_states = interested_states or {ExecutionState.COMPLETED}
        self._validate_callback()

    def _validate_callback(self) -> None:
        """Validate callback signature."""
        if not callable(self._callback):
            raise ConfigurationError("Callback must be callable")

        if inspect.iscoroutinefunction(self._callback):
            raise ConfigurationError("Async callbacks not supported")

        # Build parameter mapping for validation
        self._build_parameter_mapping()

    def _build_parameter_mapping(self) -> Dict[str, str]:
        """Build mapping from callback parameters to context attributes."""
        sig = inspect.signature(self._callback)

        # Valid parameters that can be extracted from context
        valid_params = {
            "context",
            "function_signature",
            "arguments",
            "state",
            "result",
            "local_variables",
            "metadata",
            "timestamp",
            "execution_time",
        }

        param_mapping = {}
        for param_name in sig.parameters:
            if param_name in valid_params:
                param_mapping[param_name] = param_name
            else:
                raise ConfigurationError(f"Invalid callback parameter: {param_name}")

        self._param_mapping = param_mapping
        return param_mapping

    def update(self, context: ExecutionContext) -> None:
        """Update callback with context."""
        if context.state not in self._interested_states:
            return

        # Extract callback arguments
        callback_kwargs = self._extract_callback_arguments(context)

        # Execute callback
        try:
            self._callback(**callback_kwargs)
        except Exception as e:
            # Log error but don't propagate
            logging.error(f"Callback {self._name} failed: {e}", exc_info=True)

    def _extract_callback_arguments(self, context: ExecutionContext) -> Dict[str, Any]:
        """Extract arguments for callback."""
        kwargs = {}

        context_mapping = {
            "context": context,
            "function_signature": context.function_signature,
            "arguments": context.arguments,
            "state": context.state,
            "result": context.result,
            "local_variables": context.local_variables,
            "metadata": context.metadata,
            "timestamp": context.timestamp,
            "execution_time": (
                context.result.execution_time
                if context.result and hasattr(context.result, "execution_time")
                else None
            ),
        }

        for param_name in self._param_mapping:
            if param_name in context_mapping:
                kwargs[param_name] = context_mapping[param_name]

        return kwargs
