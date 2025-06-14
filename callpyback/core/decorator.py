"""Main CallPyBack decorator implementation."""

import functools
import inspect
import traceback
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from typing_compat import Any, Callable, Dict, List, Optional, Set, Tuple

from callpyback.core.context import (
    ExecutionContext,
    ExecutionFailure,
    ExecutionResult,
    FunctionSignature,
)
from callpyback.core.state_machine import ExecutionPhase, ExecutionState, StateMachine
from callpyback.core.time_sources import SystemTimeSource
from callpyback.core.variable_extraction import (
    NoOpVariableExtractor,
    TracingVariableExtractor,
)
from callpyback.errors import ConfigurationError
from callpyback.management.error_handling import ErrorHandler
from callpyback.management.observer_manager import ErrorIsolatingObserverManager
from callpyback.protocols import Observer, TimeSource, VariableExtractor


class CallPyBack:
    """
    Main decorator class implementing advanced callback functionality.

    Features:
    - Thread-safe observer management
    - Formal state machine execution flow
    - Error isolation and circuit breaker patterns
    - Memory-safe weak reference management
    - Comprehensive variable extraction
    - Type-safe observer contracts
    """

    def __init__(
        self,
        observers: Optional[List[Observer]] = None,
        variable_names: Optional[List[str]] = None,
        exception_classes: Tuple[type, ...] = tuple(),
        default_return: Any = None,
        max_execution_time: Optional[float] = None,
        enable_async_observers: bool = False,
        max_observer_failures: int = 5,
        time_source: Optional[TimeSource] = None,
        variable_extractor: Optional[VariableExtractor] = None,
    ):
        """
        Initialize CallPyBack decorator.

        Args:
            observers: List of observers to register
            variable_names: Names of local variables to extract
            exception_classes: Exception types to catch
            default_return: Value to return on error
            max_execution_time: Maximum execution time in seconds
            enable_async_observers: Whether to run observers asynchronously
            max_observer_failures: Max failures before disabling observer
            time_source: Time source for timestamps (defaults to system time)
            variable_extractor: Variable extraction strategy
        """
        # Dependency injection for testability
        self._time_source = time_source or SystemTimeSource()
        self._variable_extractor = variable_extractor or (
            TracingVariableExtractor() if variable_names else NoOpVariableExtractor()
        )

        # Configuration
        self._variable_names = variable_names or []
        self._exception_classes = exception_classes
        self._default_return = default_return
        self._max_execution_time = max_execution_time

        # Observer management
        self._observer_manager = ErrorIsolatingObserverManager(max_observer_failures)
        self._thread_pool = (
            ThreadPoolExecutor(max_workers=4) if enable_async_observers else None
        )

        # Error handling chain
        self._error_handler = self._build_error_handler_chain()

        # Register initial observers
        for observer in observers or []:
            self.add_observer(observer)

        # Validate configuration
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        """Validate decorator configuration."""
        if not isinstance(self._exception_classes, (tuple, list)):
            raise ConfigurationError("exception_classes must be tuple or list")

        for exc_class in self._exception_classes:
            if not (inspect.isclass(exc_class) and issubclass(exc_class, Exception)):
                raise ConfigurationError(
                    f"{exc_class} is not a valid Exception subclass"
                )

        if self._max_execution_time is not None and self._max_execution_time <= 0:
            raise ConfigurationError("max_execution_time must be positive")

    def _build_error_handler_chain(self) -> ErrorHandler:
        """Build chain of responsibility for error handling."""
        # Use simple error handling that just returns default without complex validation
        from callpyback.management.error_handling import DefaultErrorHandler

        return DefaultErrorHandler(self._default_return)

    def add_observer(
        self,
        observer: Observer,
        states: Optional[Set[ExecutionState]] = None,
        phases: Optional[Set[ExecutionPhase]] = None,
    ) -> None:
        """Add observer to the system."""
        if not hasattr(observer, "update") or not hasattr(observer, "priority"):
            raise ConfigurationError("Observer must implement Observer protocol")

        # Default to completed state if no states specified
        if states is None and phases is None:
            states = {ExecutionState.COMPLETED}

        # For CallbackObserver, check if it has interested_states
        if hasattr(observer, "_interested_states") and observer._interested_states:
            states = observer._interested_states

        self._observer_manager.add_observer(observer, states, phases)

    def remove_observer(self, observer: Observer) -> None:
        """Remove observer from the system."""
        self._observer_manager.remove_observer(observer)

    def __call__(self, func: Callable) -> Callable:
        """Apply decorator to function."""
        if not callable(func):
            raise ConfigurationError("Can only decorate callable objects")

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self._execute_with_observation(func, args, kwargs)

        return wrapper

    def _execute_with_observation(
        self, func: Callable, args: Tuple[Any, ...], kwargs: Dict[str, Any]
    ) -> Any:
        """Execute function with complete observation system."""
        # Create state machine for this execution
        state_machine = StateMachine()
        start_time = self._time_source.now()

        # Create initial context
        function_signature = FunctionSignature.from_callable(func)
        arguments = self._merge_arguments(func, args, kwargs)

        context = ExecutionContext(
            function_signature=function_signature,
            arguments=arguments,
            state=ExecutionState.INITIALIZED,
            timestamp=start_time,
        )

        final_context = context  # Keep track of final context with variables

        try:
            # Phase 1: Pre-execution
            state_machine.transition_to(ExecutionState.PRE_EXECUTION)
            context = context.with_state(ExecutionState.PRE_EXECUTION)
            self._observer_manager.notify_observers(context)

            # Phase 2: Execution
            state_machine.transition_to(ExecutionState.EXECUTING)
            context = context.with_state(ExecutionState.EXECUTING)

            # Execute with variable extraction
            with self._variable_extractor.setup_extraction():
                arguments.update(arguments.pop("kwargs", {}))

                if self._max_execution_time:
                    result = self._execute_with_timeout(func, arguments)
                else:
                    result = func(**arguments)

                # Extract variables
                variables = self._variable_extractor.extract_variables(
                    self._variable_names
                )

            # Phase 3: Success
            execution_time = self._time_source.now() - start_time
            execution_result = ExecutionResult(result, execution_time)

            state_machine.transition_to(ExecutionState.POST_SUCCESS)
            context = (
                context.with_state(ExecutionState.POST_SUCCESS)
                .with_result(execution_result)
                .with_variables(variables)
            )

            final_context = context  # Update final context with variables
            self._observer_manager.notify_observers(context)
            return result

        except self._exception_classes as exc:
            # Phase 3: Failure
            execution_time = self._time_source.now() - start_time
            variables = self._variable_extractor.extract_variables(self._variable_names)

            execution_failure = ExecutionFailure(
                exception=exc,
                exception_type=type(exc),
                traceback_info=traceback.format_exc(),
                execution_time=execution_time,
            )

            if state_machine.can_transition_to(ExecutionState.POST_FAILURE):
                state_machine.transition_to(ExecutionState.POST_FAILURE)
                context = (
                    context.with_state(ExecutionState.POST_FAILURE)
                    .with_result(execution_failure)
                    .with_variables(variables)
                )

                final_context = context  # Update final context with variables
                self._observer_manager.notify_observers(context)

            # Handle error through chain of responsibility
            return self._error_handler.handle_error(exc, context)

        except Exception as unexpected_exc:
            # Unexpected error - transition to error state
            state_machine.transition_to(ExecutionState.ERROR)
            context = context.with_state(ExecutionState.ERROR)
            final_context = context
            self._observer_manager.notify_observers(context)
            raise unexpected_exc

        finally:
            # Phase 4: Completion - use final_context which has variables
            if state_machine.can_transition_to(ExecutionState.COMPLETED):
                state_machine.transition_to(ExecutionState.COMPLETED)
                final_context = final_context.with_state(ExecutionState.COMPLETED)
                self._observer_manager.notify_observers(final_context)

    def _execute_with_timeout(self, func: Callable, arguments: Dict[str, Any]) -> Any:
        """Execute function with timeout."""
        if not self._thread_pool:
            raise ConfigurationError("Thread pool required for timeout execution")

        future = self._thread_pool.submit(func, **arguments)
        try:
            return future.result(timeout=self._max_execution_time)
        except FutureTimeoutError:
            future.cancel()
            raise TimeoutError(
                f"Function execution exceeded {self._max_execution_time}s"
            )

    def _merge_arguments(
        self, func: Callable, args: Tuple[Any, ...], kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Merge positional and keyword arguments."""
        sig = inspect.signature(func)
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()
        return dict(bound_args.arguments)

    def get_metrics(self) -> Dict[str, Any]:
        """Get execution metrics from observers."""
        metrics = {
            "observer_count": self._observer_manager.get_observer_count(),
        }

        # Collect metrics from MetricsObserver if present
        for observer in self._observer_manager._observers:
            if hasattr(observer, "get_metrics"):
                metrics[f"{observer.name}_metrics"] = observer.get_metrics()

        return metrics

    def shutdown(self) -> None:
        """Clean shutdown of resources."""
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)
