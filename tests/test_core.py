"""Fixed tests for core functionality."""

import time
from unittest.mock import Mock, patch

import pytest

from callpyback.core.context import ExecutionContext, ExecutionResult, FunctionSignature
from callpyback.core.decorator import CallPyBack
from callpyback.core.state_machine import ExecutionState, StateMachine
from callpyback.core.time_sources import MockTimeSource
from callpyback.errors import ConfigurationError, StateTransitionError
from callpyback.factories import on_call, on_completion, on_failure, on_success
from callpyback.management.observer_manager import ConcurrentObserverManager
from callpyback.observers.builtin import LoggingObserver, MetricsObserver
from callpyback.observers.callback import CallbackObserver


class TestCallPyBackBasics:
    """Test basic CallPyBack functionality."""

    def test_simple_decoration(self):
        """Test basic function decoration."""
        calls = []

        @CallPyBack(
            observers=[
                on_success(lambda result: calls.append(f"success: {result.value}"))
            ]
        )
        def add_numbers(a, b):
            return a + b

        result = add_numbers(2, 3)

        assert result == 5
        assert len(calls) == 1
        assert calls[0] == "success: 5"

    def test_error_handling(self):
        """Test error handling and default return."""
        calls = []

        @CallPyBack(
            observers=[
                on_failure(lambda result: calls.append(f"error: {result.exception}"))
            ],
            default_return="error_value",
            exception_classes=(ValueError,),
        )
        def failing_function():
            raise ValueError("Something went wrong")

        result = failing_function()

        assert result == "error_value"
        assert len(calls) == 1
        assert "Something went wrong" in calls[0]

    def test_variable_extraction(self):
        """Test local variable extraction."""
        extracted_vars = []

        def capture_vars(local_variables):
            extracted_vars.append(local_variables)

        @CallPyBack(
            observers=[on_completion(capture_vars)],
            variable_names=["intermediate", "final"],
        )
        def complex_calculation(x):
            intermediate = x * 2
            final = intermediate + 10
            return final

        result = complex_calculation(5)

        assert result == 20
        assert len(extracted_vars) == 1
        assert extracted_vars[0]["intermediate"] == 10
        assert extracted_vars[0]["final"] == 20

    def test_time_control(self):
        """Test with mock time source."""
        mock_time = MockTimeSource(1000.0)
        execution_times = []

        def capture_time(result):
            execution_times.append(result.execution_time)

        decorator = CallPyBack(
            observers=[on_success(capture_time)], time_source=mock_time
        )

        @decorator
        def timed_function():
            mock_time.advance(0.5)  # Simulate 0.5 second execution
            return "done"

        result = timed_function()

        assert result == "done"
        assert len(execution_times) == 1
        assert execution_times[0] == 0.5


class TestObservers:
    """Test observer functionality."""

    def test_observer_priorities(self):
        """Test observers execute in priority order."""
        execution_order = []

        high_priority = CallbackObserver(
            lambda context: execution_order.append("high"),
            priority=100,
            interested_states={ExecutionState.COMPLETED},
        )
        low_priority = CallbackObserver(
            lambda context: execution_order.append("low"),
            priority=1,
            interested_states={ExecutionState.COMPLETED},
        )

        @CallPyBack(observers=[low_priority, high_priority])
        def test_function():
            return "result"

        test_function()

        assert execution_order == ["high", "low"]

    def test_metrics_observer(self):
        """Test built-in metrics observer."""
        metrics_observer = MetricsObserver()

        @CallPyBack(observers=[metrics_observer])
        def test_function(x):
            return x * 2

        # Execute multiple times
        for i in range(3):
            test_function(i)

        metrics = metrics_observer.get_metrics()
        assert metrics["total_executions"] == 3
        assert "test_function" in metrics["function_stats"]
        assert metrics["function_stats"]["test_function"]["calls"] == 3
        assert metrics["function_stats"]["test_function"]["successes"] == 3

    def test_observer_error_isolation(self):
        """Test that observer errors don't break execution."""

        def failing_observer(context):
            raise RuntimeError("Observer error")

        def working_observer(context):
            working_observer.called = True

        working_observer.called = False

        @CallPyBack(
            observers=[
                CallbackObserver(
                    failing_observer,
                    priority=100,
                    interested_states={ExecutionState.COMPLETED},
                ),
                CallbackObserver(
                    working_observer,
                    priority=50,
                    interested_states={ExecutionState.COMPLETED},
                ),
            ]
        )
        def test_function():
            return "success"

        # Should not raise, and working observer should still execute
        result = test_function()

        assert result == "success"
        assert working_observer.called


class TestStateManagement:
    """Test state machine functionality."""

    def test_state_transitions(self):
        """Test proper state transitions using observer manager directly."""
        states = []

        def capture_state(context):
            states.append(context.state)

        # Create observer that watches multiple states
        observer = CallbackObserver(
            capture_state,
            interested_states={
                ExecutionState.PRE_EXECUTION,
                ExecutionState.POST_SUCCESS,
                ExecutionState.COMPLETED,
            },
        )

        manager = ConcurrentObserverManager()
        manager.add_observer(
            observer,
            states={
                ExecutionState.PRE_EXECUTION,
                ExecutionState.POST_SUCCESS,
                ExecutionState.COMPLETED,
            },
        )

        # Simulate the actual state transitions that happen during execution
        signature = FunctionSignature("test_function", "test_module", ())

        # Pre-execution
        pre_context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.PRE_EXECUTION,
        )
        manager.notify_observers(pre_context)

        # Post success
        result = ExecutionResult("result", 0.1)
        success_context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.POST_SUCCESS,
            result=result,
        )
        manager.notify_observers(success_context)

        # Completed
        completed_context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.COMPLETED,
            result=result,
        )
        manager.notify_observers(completed_context)

        # Should see PRE_EXECUTION, POST_SUCCESS, COMPLETED
        assert ExecutionState.PRE_EXECUTION in states
        assert ExecutionState.POST_SUCCESS in states
        assert ExecutionState.COMPLETED in states

    def test_invalid_state_transition(self):
        """Test state machine validation."""
        state_machine = StateMachine()

        # Should be able to go from INITIALIZED to PRE_EXECUTION
        state_machine.transition_to(ExecutionState.PRE_EXECUTION)

        # Should not be able to go directly to COMPLETED
        with pytest.raises(StateTransitionError):
            state_machine.transition_to(ExecutionState.COMPLETED)


class TestConfiguration:
    """Test configuration and error cases."""

    def test_invalid_exception_classes(self):
        """Test validation of exception classes."""
        with pytest.raises(ConfigurationError):
            CallPyBack(exception_classes=("not_an_exception_class",))

    def test_invalid_observer(self):
        """Test validation of observer objects."""

        class InvalidObserver:
            pass  # Missing required methods

        with pytest.raises(ConfigurationError):
            CallPyBack(observers=[InvalidObserver()])

    def test_callback_signature_validation(self):
        """Test callback signature validation."""

        def invalid_callback(invalid_param):
            pass

        with pytest.raises(ConfigurationError):
            CallbackObserver(invalid_callback)
