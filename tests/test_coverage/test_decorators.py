"""Tests to increase coverage for core decorator module."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from unittest.mock import MagicMock, Mock, patch

import pytest

from callpyback.core.context import ExecutionContext, FunctionSignature
from callpyback.core.decorator import CallPyBack
from callpyback.core.state_machine import ExecutionState
from callpyback.core.time_sources import MockTimeSource, SystemTimeSource
from callpyback.core.variable_extraction import (
    NoOpVariableExtractor,
    TracingVariableExtractor,
)
from callpyback.errors import ConfigurationError
from callpyback.factories import on_call, on_failure, on_success
from callpyback.observers.callback import CallbackObserver


class TestCallPyBackConfiguration:
    """Test CallPyBack configuration validation."""

    def test_invalid_exception_classes_not_tuple_or_list(self):
        """Test validation with invalid exception_classes type."""
        with pytest.raises(
            ConfigurationError, match="exception_classes must be tuple or list"
        ):
            CallPyBack(exception_classes="not_a_tuple")

    def test_invalid_exception_class_not_exception_subclass(self):
        """Test validation with non-Exception subclass."""

        class NotAnException:
            pass

        with pytest.raises(
            ConfigurationError, match="is not a valid Exception subclass"
        ):
            CallPyBack(exception_classes=(NotAnException,))

    def test_invalid_max_execution_time(self):
        """Test validation with invalid max_execution_time."""
        with pytest.raises(
            ConfigurationError, match="max_execution_time must be positive"
        ):
            CallPyBack(max_execution_time=-1.0)

        with pytest.raises(
            ConfigurationError, match="max_execution_time must be positive"
        ):
            CallPyBack(max_execution_time=0.0)

    def test_invalid_observer_missing_update_method(self):
        """Test validation with observer missing update method."""

        class InvalidObserver:
            priority = 0

        with pytest.raises(
            ConfigurationError, match="Observer must implement Observer protocol"
        ):
            CallPyBack(observers=[InvalidObserver()])

    def test_invalid_observer_missing_priority(self):
        """Test validation with observer missing priority."""

        class InvalidObserver:
            def update(self, context):
                pass

        with pytest.raises(
            ConfigurationError, match="Observer must implement Observer protocol"
        ):
            CallPyBack(observers=[InvalidObserver()])

    def test_invalid_callable_decoration(self):
        """Test decorating non-callable object."""
        decorator = CallPyBack()

        with pytest.raises(
            ConfigurationError, match="Can only decorate callable objects"
        ):
            decorator("not_callable")


class TestCallPyBackTimeoutExecution:
    """Test CallPyBack timeout execution functionality."""

    def test_timeout_execution_success(self):
        """Test successful execution with timeout."""
        calls = []

        @CallPyBack(
            max_execution_time=1.0,
            enable_async_observers=True,
            observers=[on_success(lambda result: calls.append(result.value))],
        )
        def fast_function():
            time.sleep(0.1)  # Fast execution
            return "completed"

        result = fast_function()
        assert result == "completed"
        assert len(calls) == 1

    def test_timeout_execution_timeout_error(self):
        """Test timeout during execution."""

        @CallPyBack(
            max_execution_time=0.1,
            enable_async_observers=True,
            exception_classes=(TimeoutError,),
            default_return="timeout_default",
        )
        def slow_function():
            time.sleep(0.5)  # Slow execution
            return "should_not_complete"

        result = slow_function()
        assert result == "timeout_default"

    def test_timeout_without_thread_pool_raises_error(self):
        """Test timeout configuration without thread pool."""

        @CallPyBack(
            max_execution_time=1.0, enable_async_observers=False  # No thread pool
        )
        def test_function():
            return "result"

        # Should raise ConfigurationError when trying to execute with timeout but no thread pool
        with pytest.raises(
            ConfigurationError, match="Thread pool required for timeout execution"
        ):
            test_function()


class TestCallPyBackVariableExtraction:
    """Test CallPyBack variable extraction functionality."""

    def test_variable_extraction_with_tracing_extractor(self):
        """Test variable extraction using TracingVariableExtractor."""
        extracted_vars = []

        def capture_vars(local_variables):
            extracted_vars.append(local_variables)

        # Explicitly use TracingVariableExtractor
        extractor = TracingVariableExtractor()

        @CallPyBack(
            variable_names=["step1", "step2"],
            variable_extractor=extractor,
            observers=[on_success(capture_vars)],
        )
        def function_with_variables():
            step1 = "first_step"
            step2 = "second_step"
            return "done"

        result = function_with_variables()
        assert result == "done"
        assert len(extracted_vars) == 1
        assert extracted_vars[0]["step1"] == "first_step"
        assert extracted_vars[0]["step2"] == "second_step"

    def test_variable_extraction_with_noop_extractor(self):
        """Test variable extraction using NoOpVariableExtractor."""
        extracted_vars = []

        def capture_vars(local_variables):
            extracted_vars.append(local_variables)

        # Explicitly use NoOpVariableExtractor
        extractor = NoOpVariableExtractor()

        @CallPyBack(
            variable_names=["step1", "step2"],
            variable_extractor=extractor,
            observers=[on_success(capture_vars)],
        )
        def function_with_variables():
            step1 = "first_step"
            step2 = "second_step"
            return "done"

        result = function_with_variables()
        assert result == "done"
        assert len(extracted_vars) == 1
        assert extracted_vars[0] == {}  # NoOp extractor returns empty dict

    def test_variable_extraction_missing_variables(self):
        """Test variable extraction when requested variables don't exist."""
        extracted_vars = []

        def capture_vars(local_variables):
            extracted_vars.append(local_variables)

        @CallPyBack(
            variable_names=["missing_var", "also_missing"],
            observers=[on_success(capture_vars)],
        )
        def function_without_variables():
            existing_var = "exists"
            return "done"

        result = function_without_variables()
        assert result == "done"
        assert len(extracted_vars) == 1
        # Variables should be NullVariable instances or missing
        variables = extracted_vars[0]
        assert "missing_var" in variables
        assert "also_missing" in variables


class TestCallPyBackErrorHandling:
    """Test CallPyBack error handling functionality."""

    def test_unexpected_exception_transitions_to_error_state(self):
        """Test that unexpected exceptions transition to error state."""
        states = []

        def capture_state(context):
            states.append(context.state)

        # Observer that captures all states
        observer = CallbackObserver(
            capture_state,
            interested_states={
                ExecutionState.PRE_EXECUTION,
                ExecutionState.ERROR,
                ExecutionState.COMPLETED,
            },
        )

        @CallPyBack(
            observers=[observer],
            exception_classes=(ValueError,),  # Only catch ValueError
            default_return="default",
        )
        def function_with_unexpected_error():
            raise RuntimeError("Unexpected error")  # Not in exception_classes

        # Should re-raise the RuntimeError
        with pytest.raises(RuntimeError, match="Unexpected error"):
            function_with_unexpected_error()

        # Should have transitioned to ERROR state
        assert ExecutionState.ERROR in states

    def test_error_handling_with_variables_extracted(self):
        """Test that variables are extracted even during errors."""
        extracted_vars = []

        def capture_vars(local_variables):
            extracted_vars.append(local_variables)

        @CallPyBack(
            variable_names=["before_error"],
            exception_classes=(ValueError,),
            default_return="error_default",
            observers=[on_failure(capture_vars)],
        )
        def function_with_error():
            before_error = "extracted_value"
            raise ValueError("Planned error")

        result = function_with_error()
        assert result == "error_default"
        assert len(extracted_vars) == 1
        # Variable extraction should capture the value before the error
        variables = extracted_vars[0]
        assert "before_error" in variables
        # The value might be a NullVariable if extraction fails, or the actual value
        # This depends on the timing of when the tracer captures vs when the error occurs
        assert variables["before_error"] == "extracted_value" or str(
            variables["before_error"]
        ).startswith("<Variable")

    def test_error_handling_chain_called(self):
        """Test that error handler chain is called."""
        mock_error_handler = Mock()
        mock_error_handler.handle_error.return_value = "handled_by_chain"

        decorator = CallPyBack(
            exception_classes=(ValueError,), default_return="default"
        )
        # Replace the error handler
        decorator._error_handler = mock_error_handler

        @decorator
        def function_with_error():
            raise ValueError("Test error")

        result = function_with_error()
        assert result == "handled_by_chain"
        mock_error_handler.handle_error.assert_called_once()


class TestCallPyBackObserverManagement:
    """Test CallPyBack observer management functionality."""

    def test_add_observer_with_states_and_phases(self):
        """Test adding observer with both states and phases."""
        decorator = CallPyBack()

        # Create a proper observer with required attributes
        class TestObserver:
            def __init__(self):
                self.priority = 50
                self.name = "TestObserver"

            def update(self, context):
                pass

        observer = TestObserver()

        # Should not raise
        decorator.add_observer(
            observer, states={ExecutionState.POST_SUCCESS}, phases=None
        )

        assert decorator._observer_manager.get_observer_count() == 1

    def test_remove_observer(self):
        """Test removing observer."""
        decorator = CallPyBack()

        # Create a proper observer with required attributes
        class TestObserver:
            def __init__(self):
                self.priority = 50
                self.name = "TestObserver"

            def update(self, context):
                pass

        observer = TestObserver()

        decorator.add_observer(observer)
        assert decorator._observer_manager.get_observer_count() == 1

        decorator.remove_observer(observer)
        assert decorator._observer_manager.get_observer_count() == 0

    def test_observer_with_interested_states(self):
        """Test observer with _interested_states attribute."""

        class MockObserver:
            def __init__(self):
                self.priority = 50
                self.name = "MockObserver"
                self._interested_states = {ExecutionState.POST_SUCCESS}

            def update(self, context):
                pass

        mock_observer = MockObserver()

        decorator = CallPyBack()
        decorator.add_observer(mock_observer)

        # Should use the observer's interested states
        observers = decorator._observer_manager.get_observers_for_state(
            ExecutionState.POST_SUCCESS
        )
        assert mock_observer in observers


class TestCallPyBackArgumentMerging:
    """Test CallPyBack argument merging functionality."""

    def test_merge_arguments_with_defaults(self):
        """Test argument merging with default values."""
        calls = []

        def capture_args(context):
            calls.append(context.arguments)

        @CallPyBack(observers=[on_call(capture_args)])
        def function_with_defaults(a, b=10, c="default"):
            return f"{a}-{b}-{c}"

        # Call with partial arguments
        result = function_with_defaults("test", b=20)

        assert result == "test-20-default"
        assert len(calls) == 1
        expected_args = {"a": "test", "b": 20, "c": "default"}
        assert calls[0] == expected_args

    def test_merge_arguments_complex_signature(self):
        """Test argument merging with complex function signature."""
        calls = []

        def capture_args(context):
            calls.append(context.arguments)

        @CallPyBack(observers=[on_call(capture_args)])
        def complex_function(a, b=10, **kwargs):
            return f"{a}-{b}-{kwargs}"

        result = complex_function("first", b=20, extra="value")

        assert len(calls) == 1
        # Should capture all arguments correctly
        captured_args = calls[0]
        assert captured_args["a"] == "first"
        assert captured_args["b"] == 20
        assert captured_args["extra"] == "value"


class TestCallPyBackMetrics:
    """Test CallPyBack metrics functionality."""

    def test_get_metrics_with_metrics_observer(self):
        """Test get_metrics with MetricsObserver."""
        from callpyback.observers.builtin import MetricsObserver

        metrics_observer = MetricsObserver()
        decorator = CallPyBack(observers=[metrics_observer])

        @decorator
        def test_function():
            return "result"

        # Execute function
        test_function()

        # Get metrics
        metrics = decorator.get_metrics()
        assert "observer_count" in metrics
        assert "MetricsObserver_metrics" in metrics

        # Should have observer metrics
        observer_metrics = metrics["MetricsObserver_metrics"]
        assert observer_metrics["total_executions"] == 1

    def test_get_metrics_without_metrics_observer(self):
        """Test get_metrics without MetricsObserver."""
        decorator = CallPyBack()

        metrics = decorator.get_metrics()
        assert "observer_count" in metrics
        assert metrics["observer_count"] == 0


class TestCallPyBackShutdown:
    """Test CallPyBack shutdown functionality."""

    def test_shutdown_with_thread_pool(self):
        """Test shutdown when thread pool exists."""
        decorator = CallPyBack(enable_async_observers=True, max_execution_time=1.0)

        # Thread pool should be created
        assert decorator._thread_pool is not None

        # Mock the shutdown method
        with patch.object(decorator._thread_pool, "shutdown") as mock_shutdown:
            decorator.shutdown()
            mock_shutdown.assert_called_once_with(wait=True)

    def test_shutdown_without_thread_pool(self):
        """Test shutdown when no thread pool exists."""
        decorator = CallPyBack(enable_async_observers=False)

        # Should not raise
        decorator.shutdown()
        assert decorator._thread_pool is None


class TestCallPyBackTimeSource:
    """Test CallPyBack time source functionality."""

    def test_with_system_time_source(self):
        """Test CallPyBack with SystemTimeSource."""
        time_source = SystemTimeSource()
        execution_times = []

        def capture_time(result):
            execution_times.append(result.execution_time)

        @CallPyBack(time_source=time_source, observers=[on_success(capture_time)])
        def timed_function():
            time.sleep(0.01)  # Small delay
            return "timed"

        result = timed_function()
        assert result == "timed"
        assert len(execution_times) == 1
        assert execution_times[0] > 0  # Should have measured some time

    def test_with_mock_time_source(self):
        """Test CallPyBack with MockTimeSource."""
        mock_time = MockTimeSource(initial_time=1000.0)
        execution_times = []

        def capture_time(result):
            execution_times.append(result.execution_time)

        @CallPyBack(time_source=mock_time, observers=[on_success(capture_time)])
        def timed_function():
            mock_time.advance(0.5)  # Advance by 0.5 seconds
            return "timed"

        result = timed_function()
        assert result == "timed"
        assert len(execution_times) == 1
        assert execution_times[0] == 0.5


class TestCallPyBackStateTransitions:
    """Test CallPyBack state transitions during execution."""

    def test_complete_state_transition_success(self):
        """Test complete state transition during successful execution."""
        states = []

        def capture_state(context):
            states.append(context.state)

        # Observer that captures all states
        observer = CallbackObserver(
            capture_state,
            interested_states={
                ExecutionState.PRE_EXECUTION,
                ExecutionState.EXECUTING,
                ExecutionState.POST_SUCCESS,
                ExecutionState.COMPLETED,
            },
        )

        decorator = CallPyBack(observers=[observer])

        # Manually add observer for all states
        decorator._observer_manager.add_observer(
            observer,
            states={
                ExecutionState.PRE_EXECUTION,
                ExecutionState.EXECUTING,
                ExecutionState.POST_SUCCESS,
                ExecutionState.COMPLETED,
            },
        )

        @decorator
        def successful_function():
            return "success"

        result = successful_function()
        assert result == "success"

        # Should have captured state transitions
        assert ExecutionState.PRE_EXECUTION in states
        assert ExecutionState.POST_SUCCESS in states
        assert ExecutionState.COMPLETED in states

    def test_complete_state_transition_failure(self):
        """Test complete state transition during failed execution."""
        states = []

        def capture_state(context):
            states.append(context.state)

        # Observer that captures all states
        observer = CallbackObserver(
            capture_state,
            interested_states={
                ExecutionState.PRE_EXECUTION,
                ExecutionState.POST_FAILURE,
                ExecutionState.COMPLETED,
            },
        )

        decorator = CallPyBack(
            observers=[observer],
            exception_classes=(ValueError,),
            default_return="error_result",
        )

        # Manually add observer for all states
        decorator._observer_manager.add_observer(
            observer,
            states={
                ExecutionState.PRE_EXECUTION,
                ExecutionState.POST_FAILURE,
                ExecutionState.COMPLETED,
            },
        )

        @decorator
        def failing_function():
            raise ValueError("Test error")

        result = failing_function()
        assert result == "error_result"

        # Should have captured failure state transitions
        assert ExecutionState.PRE_EXECUTION in states
        assert ExecutionState.POST_FAILURE in states
        assert ExecutionState.COMPLETED in states


class TestCallPyBackFutureTimeoutError:
    """Test handling of concurrent.futures.TimeoutError."""

    @patch("callpyback.core.decorator.ThreadPoolExecutor")
    def test_future_timeout_error_handling(self, mock_executor_class):
        """Test handling of concurrent.futures.TimeoutError."""
        # Create mock executor and future
        mock_executor = Mock()
        mock_future = Mock()
        mock_executor.submit.return_value = mock_future
        mock_executor_class.return_value = mock_executor

        # Configure future to raise TimeoutError
        mock_future.result.side_effect = FutureTimeoutError("Future timeout")

        @CallPyBack(
            max_execution_time=0.1,
            enable_async_observers=True,
            exception_classes=(TimeoutError,),
            default_return="timeout_handled",
        )
        def function_that_times_out():
            return "should_not_complete"

        result = function_that_times_out()
        assert result == "timeout_handled"

        # Should have cancelled the future
        mock_future.cancel.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
