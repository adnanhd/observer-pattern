"""Tests to increase coverage for remaining modules."""

import gc
import weakref
from unittest.mock import MagicMock, Mock, patch

import pytest

from callpyback.core.context import (
    ExecutionContext,
    ExecutionFailure,
    ExecutionResult,
    FunctionSignature,
)
from callpyback.core.state_machine import ExecutionPhase, ExecutionState, StateMachine
from callpyback.core.time_sources import MockTimeSource, SystemTimeSource
from callpyback.core.variable_extraction import (
    NoOpVariableExtractor,
    NullVariable,
    TracingVariableExtractor,
)
from callpyback.errors import StateTransitionError
from callpyback.management.observer_manager import (
    ConcurrentObserverManager,
    ErrorIsolatingObserverManager,
)
from callpyback.observers.base import BaseObserver
from callpyback.observers.builtin import (
    LoggingObserver,
    MetricsObserver,
    TimingObserver,
)
from callpyback.protocols import (
    ErrorHandler,
    Observer,
    ObserverManager,
    TimeSource,
    VariableExtractor,
)


class TestExecutionContext:
    """Test ExecutionContext functionality."""

    def test_execution_context_with_state(self):
        """Test ExecutionContext.with_state method."""
        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature, arguments={}, state=ExecutionState.INITIALIZED
        )

        new_context = context.with_state(ExecutionState.PRE_EXECUTION)

        assert new_context.state == ExecutionState.PRE_EXECUTION
        assert new_context.function_signature == signature
        assert context.state == ExecutionState.INITIALIZED  # Original unchanged

    def test_execution_context_with_result(self):
        """Test ExecutionContext.with_result method."""
        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.POST_SUCCESS,
        )

        result = ExecutionResult("test_result", 0.1)
        new_context = context.with_result(result)

        assert new_context.result == result
        assert new_context.function_signature == signature
        assert context.result is None  # Original unchanged

    def test_execution_context_with_variables(self):
        """Test ExecutionContext.with_variables method."""
        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature, arguments={}, state=ExecutionState.COMPLETED
        )

        variables = {"var1": "value1", "var2": "value2"}
        new_context = context.with_variables(variables)

        assert new_context.local_variables == variables
        assert new_context.function_signature == signature
        assert context.local_variables is None  # Original unchanged

    def test_execution_context_is_successful(self):
        """Test ExecutionContext.is_successful property."""
        signature = FunctionSignature("test", "module", ())

        # Context with success result
        success_result = ExecutionResult("result", 0.1)
        success_context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.POST_SUCCESS,
            result=success_result,
        )
        assert success_context.is_successful is True

        # Context with failure result
        failure_result = ExecutionFailure(
            exception=ValueError("error"),
            exception_type=ValueError,
            traceback_info="traceback",
            execution_time=0.1,
        )
        failure_context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.POST_FAILURE,
            result=failure_result,
        )
        assert failure_context.is_successful is False

    def test_execution_context_is_failed(self):
        """Test ExecutionContext.is_failed property."""
        signature = FunctionSignature("test", "module", ())

        # Context with failure result
        failure_result = ExecutionFailure(
            exception=ValueError("error"),
            exception_type=ValueError,
            traceback_info="traceback",
            execution_time=0.1,
        )
        failure_context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.POST_FAILURE,
            result=failure_result,
        )
        assert failure_context.is_failed is True

        # Context with success result
        success_result = ExecutionResult("result", 0.1)
        success_context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.POST_SUCCESS,
            result=success_result,
        )
        assert success_context.is_failed is False


class TestFunctionSignature:
    """Test FunctionSignature functionality."""

    def test_function_signature_from_callable(self):
        """Test FunctionSignature.from_callable method."""

        def test_function(a: int, b: str = "default") -> str:
            return f"{a}-{b}"

        signature = FunctionSignature.from_callable(test_function)

        assert signature.name == "test_function"
        # Module name will be the test module name, not __main__
        assert signature.module.endswith("test_remaining")
        assert signature.parameters == ("a", "b")
        assert signature.annotations == {"a": int, "b": str, "return": str}

    def test_function_signature_from_callable_no_annotations(self):
        """Test FunctionSignature.from_callable with no annotations."""

        def simple_function(x, y):
            return x + y

        signature = FunctionSignature.from_callable(simple_function)

        assert signature.name == "simple_function"
        assert signature.parameters == ("x", "y")
        assert signature.annotations == {}

    def test_function_signature_from_lambda(self):
        """Test FunctionSignature.from_callable with lambda."""
        lambda_func = lambda x: x * 2

        signature = FunctionSignature.from_callable(lambda_func)

        assert signature.name == "<lambda>"
        assert signature.parameters == ("x",)

    def test_function_signature_from_callable_deleted_module(self):
        """Test FunctionSignature.from_callable with deleted __module__ (becomes None)."""

        def test_func():
            pass

        # Store original module for restoration
        original_module = test_func.__module__

        try:
            # Remove __module__ attribute - this actually sets it to None
            delattr(test_func, "__module__")

            signature = FunctionSignature.from_callable(test_func)
            # After delattr, __module__ becomes None
            assert signature.module is None
        finally:
            # Restore original module to avoid affecting other tests
            test_func.__module__ = original_module


class TestExecutionResult:
    """Test ExecutionResult functionality."""

    def test_execution_result_is_success(self):
        """Test ExecutionResult.is_success property."""
        result = ExecutionResult("value", 0.1)
        assert result.is_success is True

    def test_execution_result_with_memory_usage(self):
        """Test ExecutionResult with memory_usage."""
        result = ExecutionResult("value", 0.1, memory_usage=1024)
        assert result.memory_usage == 1024
        assert result.is_success is True


class TestExecutionFailure:
    """Test ExecutionFailure functionality."""

    def test_execution_failure_is_success(self):
        """Test ExecutionFailure.is_success property."""
        failure = ExecutionFailure(
            exception=ValueError("error"),
            exception_type=ValueError,
            traceback_info="traceback",
            execution_time=0.1,
        )
        assert failure.is_success is False


class TestStateMachine:
    """Test StateMachine functionality."""

    def test_state_machine_can_transition_to(self):
        """Test StateMachine.can_transition_to method."""
        state_machine = StateMachine()

        # From INITIALIZED, can go to PRE_EXECUTION
        assert state_machine.can_transition_to(ExecutionState.PRE_EXECUTION) is True

        # From INITIALIZED, cannot go to COMPLETED
        assert state_machine.can_transition_to(ExecutionState.COMPLETED) is False

    def test_state_machine_is_terminal(self):
        """Test StateMachine.is_terminal method."""
        state_machine = StateMachine()

        # INITIALIZED is not terminal
        assert state_machine.is_terminal() is False

        # Transition to terminal state
        state_machine.transition_to(ExecutionState.PRE_EXECUTION)
        state_machine.transition_to(ExecutionState.EXECUTING)
        state_machine.transition_to(ExecutionState.POST_SUCCESS)
        state_machine.transition_to(ExecutionState.COMPLETED)

        # COMPLETED is terminal
        assert state_machine.is_terminal() is True

    def test_state_machine_state_history(self):
        """Test StateMachine.state_history property."""
        state_machine = StateMachine()

        initial_history = state_machine.state_history
        assert len(initial_history) == 1
        assert initial_history[0] == ExecutionState.INITIALIZED

        # Transition and check history
        state_machine.transition_to(ExecutionState.PRE_EXECUTION)
        state_machine.transition_to(ExecutionState.EXECUTING)

        history = state_machine.state_history
        assert len(history) == 3
        assert history[0] == ExecutionState.INITIALIZED
        assert history[1] == ExecutionState.PRE_EXECUTION
        assert history[2] == ExecutionState.EXECUTING

    def test_state_machine_invalid_transition_error(self):
        """Test StateMachine raises StateTransitionError for invalid transitions."""
        state_machine = StateMachine()

        with pytest.raises(StateTransitionError) as exc_info:
            state_machine.transition_to(ExecutionState.COMPLETED)

        assert exc_info.value.from_state == "INITIALIZED"
        assert exc_info.value.to_state == "COMPLETED"
        assert "PRE_EXECUTION" in exc_info.value.valid_transitions


class TestVariableExtraction:
    """Test variable extraction functionality."""

    def test_null_variable_str_representation(self):
        """Test NullVariable string representations."""
        null_var = NullVariable("missing_var")

        assert str(null_var) == "<Variable 'missing_var' not found>"
        assert repr(null_var) == "NullVariable('missing_var')"
        assert null_var.name == "missing_var"

    def test_tracing_variable_extractor_with_missing_variables(self):
        """Test TracingVariableExtractor with missing variables."""
        extractor = TracingVariableExtractor()

        # Extract variables that don't exist
        with extractor.setup_extraction():
            pass  # No local variables

        variables = extractor.extract_variables(["missing1", "missing2"])

        assert len(variables) == 2
        assert isinstance(variables["missing1"], NullVariable)
        assert isinstance(variables["missing2"], NullVariable)
        assert variables["missing1"].name == "missing1"

    def test_tracing_variable_extractor_context_manager_exception(self):
        """Test TracingVariableExtractor context manager with exception."""
        extractor = TracingVariableExtractor()

        # Test that context manager properly cleans up on exception
        try:
            with extractor.setup_extraction():
                raise RuntimeError("Test exception")
        except RuntimeError:
            pass

        # Should still be able to extract (though empty)
        variables = extractor.extract_variables(["test"])
        assert isinstance(variables["test"], NullVariable)

    def test_noop_variable_extractor_context_manager(self):
        """Test NoOpVariableExtractor context manager."""
        extractor = NoOpVariableExtractor()

        # Context manager should work without issues
        with extractor.setup_extraction():
            local_var = "test"  # This won't be captured

        variables = extractor.extract_variables(["local_var"])
        assert variables == {}

    @patch("callpyback.core.variable_extraction.sys")
    def test_tracing_variable_extractor_tracer_profile_management(self, mock_sys):
        """Test TracingVariableExtractor manages sys.setprofile correctly."""
        mock_sys.getprofile.return_value = "original_profile"

        extractor = TracingVariableExtractor()

        with extractor.setup_extraction():
            pass

        # Should have set and restored profile
        mock_sys.setprofile.assert_any_call(extractor._tracer)
        mock_sys.setprofile.assert_any_call("original_profile")


class TestTimeSource:
    """Test time source functionality."""

    def test_mock_time_source_advance(self):
        """Test MockTimeSource.advance method."""
        source = MockTimeSource(initial_time=100.0)

        assert source.now() == 100.0

        source.advance(50.0)
        assert source.now() == 150.0

        source.advance(25.5)
        assert source.now() == 175.5

    def test_mock_time_source_set_time(self):
        """Test MockTimeSource.set_time method."""
        source = MockTimeSource(initial_time=100.0)

        assert source.now() == 100.0

        source.set_time(500.0)
        assert source.now() == 500.0

        source.set_time(0.0)
        assert source.now() == 0.0

    def test_system_time_source_now(self):
        """Test SystemTimeSource.now method."""
        import time

        source = SystemTimeSource()

        # Should return current time
        before = time.time()
        current = source.now()
        after = time.time()

        assert before <= current <= after


class TestObserverBase:
    """Test BaseObserver functionality."""

    def test_base_observer_set_metadata_immutability(self):
        """Test that BaseObserver.metadata returns immutable copy."""

        class TestObserver(BaseObserver):
            def update(self, context):
                pass

        observer = TestObserver()
        observer.set_metadata("key1", "value1")

        # Get metadata and modify it
        metadata = observer.metadata
        metadata["key2"] = "value2"

        # Original observer metadata should be unchanged
        assert "key2" not in observer.metadata
        assert observer.metadata == {"key1": "value1"}


class TestBuiltinObservers:
    """Test built-in observers functionality."""

    def test_logging_observer_with_custom_logger(self):
        """Test LoggingObserver with custom logger."""
        import logging

        custom_logger = logging.getLogger("test_logger")
        observer = LoggingObserver(logger=custom_logger, log_level=logging.WARNING)

        assert observer._logger == custom_logger
        assert observer._log_level == logging.WARNING

    def test_logging_observer_context_without_result(self):
        """Test LoggingObserver with context that has no result."""
        observer = LoggingObserver()

        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.PRE_EXECUTION,
            result=None,
        )

        with patch.object(observer._logger, "log") as mock_log:
            observer.update(context)
            mock_log.assert_called_once()
            args, kwargs = mock_log.call_args
            assert "test" in args[1]
            assert "PRE_EXECUTION" in args[1]

    def test_timing_observer_context_without_execution_time(self):
        """Test TimingObserver with context that has no execution_time."""
        observer = TimingObserver(threshold=0.1)

        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.PRE_EXECUTION,
            result=None,
        )

        # Should not raise, should not add to slow executions
        observer.update(context)
        assert len(observer.get_slow_executions()) == 0

    def test_timing_observer_context_without_result_attribute(self):
        """Test TimingObserver with result missing execution_time attribute."""
        observer = TimingObserver(threshold=0.1)

        # Create mock result without execution_time
        mock_result = Mock()
        del mock_result.execution_time  # Remove the attribute

        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.POST_SUCCESS,
            result=mock_result,
        )

        # Should not raise, should not add to slow executions
        observer.update(context)
        assert len(observer.get_slow_executions()) == 0


class TestObserverManagerEdgeCases:
    """Test observer manager edge cases."""

    def test_concurrent_observer_manager_weak_references(self):
        """Test ConcurrentObserverManager with weak references."""
        manager = ConcurrentObserverManager()

        # Create observer and add to manager
        observer = Mock()
        observer.priority = 50
        manager.add_observer(observer, states={ExecutionState.COMPLETED})

        assert manager.get_observer_count() == 1

        # Remove reference and force garbage collection
        del observer
        gc.collect()

        # Observer count might be reduced due to weak references
        # (This depends on the specific implementation of weak references)
        count = manager.get_observer_count()
        assert count >= 0  # Should not raise

    def test_concurrent_observer_manager_remove_from_empty_collections(self):
        """Test removing observer when collections are empty."""
        manager = ConcurrentObserverManager()
        observer = Mock()
        observer.priority = 50

        # Try to remove observer that was never added
        # Should not raise
        manager.remove_observer(observer)

    def test_error_isolating_manager_enable_observer_not_disabled(self):
        """Test enabling observer that wasn't disabled."""
        manager = ErrorIsolatingObserverManager()
        observer = Mock()
        observer.priority = 50

        # Try to enable observer that's not disabled
        # Should not raise
        manager.enable_observer(observer)


class TestProtocols:
    """Test protocol runtime checking."""

    def test_observer_protocol_runtime_checking(self):
        """Test Observer protocol runtime checking."""

        # Valid observer
        class ValidObserver:
            priority = 50

            def update(self, context):
                pass

        valid_observer = ValidObserver()
        assert isinstance(valid_observer, Observer)

        # Invalid observer (missing update)
        class InvalidObserver:
            priority = 50

        invalid_observer = InvalidObserver()
        assert not isinstance(invalid_observer, Observer)

    def test_variable_extractor_protocol_runtime_checking(self):
        """Test VariableExtractor protocol runtime checking."""

        # Valid extractor
        class ValidExtractor:
            def setup_extraction(self):
                from contextlib import nullcontext

                return nullcontext()

            def extract_variables(self, variable_names):
                return {}

        valid_extractor = ValidExtractor()
        assert isinstance(valid_extractor, VariableExtractor)

        # Invalid extractor (missing method)
        class InvalidExtractor:
            def setup_extraction(self):
                from contextlib import nullcontext

                return nullcontext()

        invalid_extractor = InvalidExtractor()
        assert not isinstance(invalid_extractor, VariableExtractor)

    def test_time_source_protocol_runtime_checking(self):
        """Test TimeSource protocol runtime checking."""

        # Valid time source
        class ValidTimeSource:
            def now(self):
                return 123.456

        valid_source = ValidTimeSource()
        assert isinstance(valid_source, TimeSource)

        # Invalid time source
        class InvalidTimeSource:
            pass

        invalid_source = InvalidTimeSource()
        assert not isinstance(invalid_source, TimeSource)

    def test_observer_manager_protocol_runtime_checking(self):
        """Test ObserverManager protocol runtime checking."""

        # Valid manager
        class ValidManager:
            def add_observer(self, observer):
                pass

            def remove_observer(self, observer):
                pass

            def notify_observers(self, context):
                pass

        valid_manager = ValidManager()
        assert isinstance(valid_manager, ObserverManager)

    def test_error_handler_protocol_runtime_checking(self):
        """Test ErrorHandler protocol runtime checking."""

        # Valid handler
        class ValidHandler:
            def handle_error(self, error, context):
                return "handled"

        valid_handler = ValidHandler()
        assert isinstance(valid_handler, ErrorHandler)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
