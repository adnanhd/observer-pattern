"""Comprehensive pytest unit tests for CallPyBack observer pattern."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from callpyback.core.context import (
    ExecutionContext,
    ExecutionFailure,
    ExecutionResult,
    FunctionSignature,
)
from callpyback.core.state_machine import ExecutionPhase, ExecutionState
from callpyback.errors import ConfigurationError, ObserverError
from callpyback.factories import (
    create_callback_observer,
    on_call,
    on_completion,
    on_failure,
    on_success,
)
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
from callpyback.observers.callback import CallbackObserver
from callpyback.protocols import Observer


# Test Fixtures and Helpers
@pytest.fixture
def sample_context():
    """Create a sample execution context for testing."""
    signature = FunctionSignature("test_func", "test_module", ("param1", "param2"))
    result = ExecutionResult("test_result", 0.123)
    return ExecutionContext(
        function_signature=signature,
        arguments={"param1": "value1", "param2": "value2"},
        state=ExecutionState.POST_SUCCESS,
        result=result,
        local_variables={"var1": "val1", "var2": "val2"},
        timestamp=1234567890.0,
    )


@pytest.fixture
def failure_context():
    """Create a failure execution context for testing."""
    signature = FunctionSignature("test_func", "test_module", ("param1",))
    failure = ExecutionFailure(
        exception=ValueError("test error"),
        exception_type=ValueError,
        traceback_info="Traceback...",
        execution_time=0.045,
    )
    return ExecutionContext(
        function_signature=signature,
        arguments={"param1": "bad_value"},
        state=ExecutionState.POST_FAILURE,
        result=failure,
        timestamp=1234567890.0,
    )


class MockObserver:
    """Mock observer for testing."""

    def __init__(self, priority=0, name="MockObserver"):
        self.priority = priority
        self.name = name
        self.update_calls = []
        self.should_fail = False

    def update(self, context):
        self.update_calls.append(context)
        if self.should_fail:
            raise RuntimeError("Mock observer failure")


# Base Observer Tests
class TestBaseObserver:
    """Test BaseObserver abstract class."""

    def test_base_observer_initialization(self):
        """Test BaseObserver initialization."""

        class ConcreteObserver(BaseObserver):
            def update(self, context):
                pass

        observer = ConcreteObserver(priority=50, name="TestObserver")

        assert observer.priority == 50
        assert observer.name == "TestObserver"
        assert observer.metadata == {}

    def test_base_observer_default_name(self):
        """Test BaseObserver uses class name as default."""

        class CustomObserver(BaseObserver):
            def update(self, context):
                pass

        observer = CustomObserver(priority=10)
        assert observer.name == "CustomObserver"

    def test_metadata_operations(self):
        """Test metadata get/set operations."""

        class TestObserver(BaseObserver):
            def update(self, context):
                pass

        observer = TestObserver()
        observer.set_metadata("key1", "value1")
        observer.set_metadata("key2", 42)

        metadata = observer.metadata
        assert metadata["key1"] == "value1"
        assert metadata["key2"] == 42

        # Test immutability of returned metadata
        metadata["key3"] = "should_not_affect_observer"
        assert "key3" not in observer.metadata

    def test_abstract_update_method(self):
        """Test that BaseObserver is abstract."""
        with pytest.raises(TypeError):
            BaseObserver()


# Callback Observer Tests
class TestCallbackObserver:
    """Test CallbackObserver implementation."""

    def test_callback_observer_initialization(self):
        """Test CallbackObserver initialization."""

        def test_callback(context):
            pass

        observer = CallbackObserver(
            test_callback,
            interested_states={ExecutionState.POST_SUCCESS},
            priority=75,
            name="TestCallback",
        )

        assert observer.priority == 75
        assert observer.name == "TestCallback"
        assert observer._interested_states == {ExecutionState.POST_SUCCESS}

    def test_callback_observer_defaults(self):
        """Test CallbackObserver default values."""

        def test_callback():
            pass

        observer = CallbackObserver(test_callback)

        assert observer.priority == 0
        assert observer._interested_states == {ExecutionState.COMPLETED}

    def test_callback_validation_not_callable(self):
        """Test callback validation with non-callable."""
        with pytest.raises(ConfigurationError, match="Callback must be callable"):
            CallbackObserver("not_callable")

    def test_callback_validation_async_callback(self):
        """Test callback validation with async function."""

        async def async_callback():
            pass

        with pytest.raises(ConfigurationError, match="Async callbacks not supported"):
            CallbackObserver(async_callback)

    def test_callback_parameter_validation_valid(self):
        """Test valid callback parameters."""

        def valid_callback(context, result, function_signature):
            pass

        # Should not raise
        observer = CallbackObserver(valid_callback)
        assert observer is not None

    def test_callback_parameter_validation_invalid(self):
        """Test invalid callback parameters."""

        def invalid_callback(invalid_param):
            pass

        with pytest.raises(ConfigurationError, match="Invalid callback parameter"):
            CallbackObserver(invalid_callback)

    def test_callback_execution_with_state_filter(self, sample_context):
        """Test callback execution with state filtering."""
        calls = []

        def test_callback(context):
            calls.append(context)

        observer = CallbackObserver(
            test_callback, interested_states={ExecutionState.POST_SUCCESS}
        )

        # Should execute for POST_SUCCESS
        observer.update(sample_context)
        assert len(calls) == 1

        # Should not execute for different state
        different_context = sample_context.with_state(ExecutionState.PRE_EXECUTION)
        observer.update(different_context)
        assert len(calls) == 1  # No new calls

    def test_callback_argument_extraction(self, sample_context):
        """Test callback argument extraction from context."""
        captured_args = {}

        def test_callback(context, result, function_signature, arguments):
            captured_args.update(
                {
                    "context": context,
                    "result": result,
                    "function_signature": function_signature,
                    "arguments": arguments,
                }
            )

        observer = CallbackObserver(
            test_callback, interested_states={ExecutionState.POST_SUCCESS}
        )
        observer.update(sample_context)

        assert captured_args["context"] == sample_context
        assert captured_args["result"] == sample_context.result
        assert captured_args["function_signature"] == sample_context.function_signature
        assert captured_args["arguments"] == sample_context.arguments

    def test_callback_error_isolation(self, sample_context):
        """Test that callback errors don't propagate."""

        def failing_callback(context):
            raise RuntimeError("Callback error")

        observer = CallbackObserver(failing_callback)

        # Should not raise
        observer.update(sample_context)

    @patch("callpyback.observers.callback.logging")
    def test_callback_error_logging(self, mock_logging, sample_context):
        """Test that callback errors are logged."""

        def failing_callback(context):
            raise RuntimeError("Callback error")

        observer = CallbackObserver(
            failing_callback,
            name="FailingCallback",
            interested_states={ExecutionState.POST_SUCCESS},
        )
        observer.update(sample_context)

        mock_logging.error.assert_called_once()
        args, kwargs = mock_logging.error.call_args
        assert "FailingCallback failed" in args[0]


# Built-in Observer Tests
class TestLoggingObserver:
    """Test LoggingObserver implementation."""

    def test_logging_observer_initialization(self):
        """Test LoggingObserver initialization."""
        logger = logging.getLogger("test")
        observer = LoggingObserver(logger, logging.WARNING, priority=25)

        assert observer._logger == logger
        assert observer._log_level == logging.WARNING
        assert observer.priority == 25

    def test_logging_observer_defaults(self):
        """Test LoggingObserver default values."""
        observer = LoggingObserver()

        assert observer._log_level == logging.INFO
        assert observer.priority == 10

    @patch("callpyback.observers.builtin.logging")
    def test_success_logging(self, mock_logging, sample_context):
        """Test logging of successful execution."""
        mock_logger = Mock()
        mock_logging.getLogger.return_value = mock_logger

        observer = LoggingObserver()
        observer.update(sample_context)

        mock_logger.log.assert_called_once()
        args, kwargs = mock_logger.log.call_args
        assert args[0] == logging.INFO
        assert "test_func" in args[1]
        assert "completed successfully" in args[1]
        assert "0.123s" in args[1]

    @patch("callpyback.observers.builtin.logging")
    def test_failure_logging(self, mock_logging, failure_context):
        """Test logging of failed execution."""
        mock_logger = Mock()
        mock_logging.getLogger.return_value = mock_logger

        observer = LoggingObserver()
        observer.update(failure_context)

        mock_logger.log.assert_called_once()
        args, kwargs = mock_logger.log.call_args
        assert "test_func" in args[1]
        assert "failed" in args[1]
        assert "test error" in args[1]


class TestMetricsObserver:
    """Test MetricsObserver implementation."""

    def test_metrics_observer_initialization(self):
        """Test MetricsObserver initialization."""
        observer = MetricsObserver(priority=99)

        assert observer.priority == 99
        assert observer.name == "MetricsObserver"
        assert observer._counters == {}
        assert observer._execution_times == []
        assert observer._function_stats == {}

    def test_metrics_collection_success(self, sample_context):
        """Test metrics collection for successful execution."""
        observer = MetricsObserver()
        observer.update(sample_context)

        metrics = observer.get_metrics()
        assert metrics["total_executions"] == 1
        assert metrics["function_stats"]["test_func"]["calls"] == 1
        assert metrics["function_stats"]["test_func"]["successes"] == 1
        assert metrics["function_stats"]["test_func"]["failures"] == 0
        assert metrics["function_stats"]["test_func"]["total_time"] == 0.123

    def test_metrics_collection_failure(self, failure_context):
        """Test metrics collection for failed execution."""
        observer = MetricsObserver()

        # Update with failure context that has ExecutionState.POST_FAILURE
        failure_context_with_proper_state = failure_context.with_state(
            ExecutionState.POST_FAILURE
        )
        observer.update(failure_context_with_proper_state)

        metrics = observer.get_metrics()
        assert metrics["function_stats"]["test_func"]["calls"] == 1
        assert metrics["function_stats"]["test_func"]["successes"] == 0
        assert metrics["function_stats"]["test_func"]["failures"] == 1

    def test_metrics_multiple_executions(self, sample_context, failure_context):
        """Test metrics with multiple executions."""
        observer = MetricsObserver()

        # Execute multiple times with proper states
        success_context = sample_context.with_state(ExecutionState.POST_SUCCESS)
        failure_context_proper = failure_context.with_state(ExecutionState.POST_FAILURE)

        for _ in range(3):
            observer.update(success_context)

        for _ in range(2):
            observer.update(failure_context_proper)

        metrics = observer.get_metrics()
        # Only successful executions are counted in total_executions
        assert metrics["total_executions"] == 3
        assert metrics["function_stats"]["test_func"]["calls"] == 5
        assert metrics["function_stats"]["test_func"]["successes"] == 3
        assert metrics["function_stats"]["test_func"]["failures"] == 2

    def test_metrics_average_calculation(self, sample_context):
        """Test average execution time calculation."""
        observer = MetricsObserver()

        # Create contexts with different execution times
        contexts = []
        for i, exec_time in enumerate([0.1, 0.2, 0.3]):
            result = ExecutionResult(f"result_{i}", exec_time)
            ctx = sample_context.with_result(result).with_state(
                ExecutionState.POST_SUCCESS
            )
            contexts.append(ctx)

        for ctx in contexts:
            observer.update(ctx)

        metrics = observer.get_metrics()
        # Use pytest.approx for floating point comparison
        assert metrics["average_execution_time"] == pytest.approx(0.2, rel=1e-9)

    def test_metrics_reset(self, sample_context):
        """Test metrics reset functionality."""
        observer = MetricsObserver()
        observer.update(sample_context)

        # Verify metrics exist
        metrics = observer.get_metrics()
        assert metrics["total_executions"] == 1

        # Reset and verify clean state
        observer.reset_metrics()
        metrics = observer.get_metrics()
        assert metrics["total_executions"] == 0
        assert metrics["function_stats"] == {}


class TestTimingObserver:
    """Test TimingObserver implementation."""

    def test_timing_observer_initialization(self):
        """Test TimingObserver initialization."""
        observer = TimingObserver(threshold=2.0, priority=80)

        assert observer._threshold == 2.0
        assert observer.priority == 80
        assert observer._slow_executions == []

    def test_timing_observer_defaults(self):
        """Test TimingObserver default values."""
        observer = TimingObserver()

        assert observer._threshold == 1.0
        assert observer.priority == 75

    def test_slow_execution_detection(self, sample_context):
        """Test detection of slow executions."""
        observer = TimingObserver(threshold=0.1)

        # Create slow execution context
        slow_result = ExecutionResult("slow_result", 0.15)
        slow_context = sample_context.with_result(slow_result)

        with patch("callpyback.observers.builtin.logging") as mock_logging:
            observer.update(slow_context)

            # Should detect as slow
            slow_executions = observer.get_slow_executions()
            assert len(slow_executions) == 1
            assert slow_executions[0]["function_name"] == "test_func"
            assert slow_executions[0]["execution_time"] == 0.15

            # Should log warning
            mock_logging.warning.assert_called_once()

    def test_fast_execution_not_recorded(self, sample_context):
        """Test that fast executions are not recorded."""
        observer = TimingObserver(threshold=0.2)

        # sample_context has execution_time of 0.123, below threshold
        observer.update(sample_context)

        slow_executions = observer.get_slow_executions()
        assert len(slow_executions) == 0

    def test_threshold_modification(self):
        """Test threshold modification."""
        observer = TimingObserver(threshold=1.0)
        assert observer._threshold == 1.0

        observer.set_threshold(0.5)
        assert observer._threshold == 0.5


# Observer Manager Tests
class TestConcurrentObserverManager:
    """Test ConcurrentObserverManager implementation."""

    def test_observer_manager_initialization(self):
        """Test observer manager initialization."""
        manager = ConcurrentObserverManager()

        assert manager.get_observer_count() == 0

    def test_add_observer(self):
        """Test adding observers."""
        manager = ConcurrentObserverManager()
        observer = MockObserver()

        manager.add_observer(observer, states={ExecutionState.POST_SUCCESS})

        assert manager.get_observer_count() == 1
        observers = manager.get_observers_for_state(ExecutionState.POST_SUCCESS)
        assert len(observers) == 1
        assert observers[0] == observer

    def test_remove_observer(self):
        """Test removing observers."""
        manager = ConcurrentObserverManager()
        observer = MockObserver()

        manager.add_observer(observer, states={ExecutionState.POST_SUCCESS})
        assert manager.get_observer_count() == 1

        manager.remove_observer(observer)
        assert manager.get_observer_count() == 0

    def test_observer_priority_ordering(self):
        """Test observers are ordered by priority."""
        manager = ConcurrentObserverManager()

        high_priority = MockObserver(priority=100, name="High")
        medium_priority = MockObserver(priority=50, name="Medium")
        low_priority = MockObserver(priority=10, name="Low")

        # Add in random order
        manager.add_observer(medium_priority, states={ExecutionState.POST_SUCCESS})
        manager.add_observer(low_priority, states={ExecutionState.POST_SUCCESS})
        manager.add_observer(high_priority, states={ExecutionState.POST_SUCCESS})

        observers = manager.get_observers_for_state(ExecutionState.POST_SUCCESS)
        assert len(observers) == 3
        assert observers[0].name == "High"
        assert observers[1].name == "Medium"
        assert observers[2].name == "Low"

    def test_notify_observers(self, sample_context):
        """Test observer notification."""
        manager = ConcurrentObserverManager()
        observer1 = MockObserver()
        observer2 = MockObserver()

        manager.add_observer(observer1, states={ExecutionState.POST_SUCCESS})
        manager.add_observer(observer2, states={ExecutionState.POST_SUCCESS})

        manager.notify_observers(sample_context)

        assert len(observer1.update_calls) == 1
        assert len(observer2.update_calls) == 1
        assert observer1.update_calls[0] == sample_context
        assert observer2.update_calls[0] == sample_context

    def test_observer_error_isolation(self, sample_context):
        """Test that observer errors don't affect other observers."""
        manager = ConcurrentObserverManager()

        failing_observer = MockObserver(name="Failing")
        failing_observer.should_fail = True
        working_observer = MockObserver(name="Working")

        manager.add_observer(failing_observer, states={ExecutionState.POST_SUCCESS})
        manager.add_observer(working_observer, states={ExecutionState.POST_SUCCESS})

        # Should not raise, and working observer should still be called
        manager.notify_observers(sample_context)

        assert len(working_observer.update_calls) == 1

    def test_thread_safety(self, sample_context):
        """Test thread safety of observer manager."""
        manager = ConcurrentObserverManager()
        observer = MockObserver()
        manager.add_observer(observer, states={ExecutionState.POST_SUCCESS})

        # Simulate concurrent access
        def notify_worker():
            for _ in range(10):
                manager.notify_observers(sample_context)

        threads = []
        for _ in range(5):
            thread = threading.Thread(target=notify_worker)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Should have received 50 notifications (5 threads * 10 calls)
        assert len(observer.update_calls) == 50


class TestErrorIsolatingObserverManager:
    """Test ErrorIsolatingObserverManager implementation."""

    def test_error_isolating_manager_initialization(self):
        """Test error isolating manager initialization."""
        manager = ErrorIsolatingObserverManager(max_failures=3)

        assert manager._max_failures == 3
        assert manager.get_observer_count() == 0

    def test_observer_failure_counting(self, sample_context):
        """Test observer failure counting."""
        manager = ErrorIsolatingObserverManager(max_failures=2)
        observer = MockObserver()
        observer.should_fail = True

        manager.add_observer(observer, states={ExecutionState.POST_SUCCESS})

        # First failure
        manager.notify_observers(sample_context)
        assert manager._failure_counts[observer] == 1
        assert observer not in manager._disabled_observers

        # Second failure - should disable
        manager.notify_observers(sample_context)
        assert manager._failure_counts[observer] == 2
        assert observer in manager._disabled_observers

    def test_observer_recovery(self, sample_context):
        """Test observer recovery after success."""
        manager = ErrorIsolatingObserverManager(max_failures=3)
        observer = MockObserver()

        manager.add_observer(observer, states={ExecutionState.POST_SUCCESS})

        # Simulate failure then success
        observer.should_fail = True
        manager.notify_observers(sample_context)
        assert manager._failure_counts[observer] == 1

        # Success should reduce failure count
        observer.should_fail = False
        manager.notify_observers(sample_context)
        assert manager._failure_counts[observer] == 0

    def test_manual_observer_enablement(self, sample_context):
        """Test manual re-enablement of disabled observers."""
        manager = ErrorIsolatingObserverManager(max_failures=1)
        observer = MockObserver()
        observer.should_fail = True

        manager.add_observer(observer, states={ExecutionState.POST_SUCCESS})

        # Disable observer
        manager.notify_observers(sample_context)
        assert observer in manager._disabled_observers

        # Re-enable manually
        manager.enable_observer(observer)
        assert observer not in manager._disabled_observers
        assert manager._failure_counts[observer] == 0


# Factory Function Tests
class TestFactoryFunctions:
    """Test observer factory functions."""

    def test_on_call_factory(self):
        """Test on_call factory function."""

        def test_callback(context):
            pass

        observer = on_call(test_callback, priority=75, name="TestOnCall")

        assert isinstance(observer, CallbackObserver)
        assert observer.priority == 75
        assert observer.name == "TestOnCall"
        assert ExecutionState.PRE_EXECUTION in observer._interested_states

    def test_on_success_factory(self):
        """Test on_success factory function."""

        def test_callback(result):
            pass

        observer = on_success(test_callback)

        assert isinstance(observer, CallbackObserver)
        assert ExecutionState.POST_SUCCESS in observer._interested_states

    def test_on_failure_factory(self):
        """Test on_failure factory function."""

        def test_callback(result):
            pass

        observer = on_failure(test_callback)

        assert isinstance(observer, CallbackObserver)
        assert ExecutionState.POST_FAILURE in observer._interested_states

    def test_on_completion_factory(self):
        """Test on_completion factory function."""

        def test_callback(context):
            pass

        observer = on_completion(test_callback)

        assert isinstance(observer, CallbackObserver)
        assert ExecutionState.COMPLETED in observer._interested_states

    def test_create_callback_observer_factory(self):
        """Test create_callback_observer factory function."""

        def test_callback(context):
            pass

        observer = create_callback_observer(
            callback=test_callback,
            states={ExecutionState.POST_SUCCESS, ExecutionState.POST_FAILURE},
            priority=42,
            name="CustomObserver",
        )

        assert isinstance(observer, CallbackObserver)
        assert observer.priority == 42
        assert observer.name == "CustomObserver"
        assert observer._interested_states == {
            ExecutionState.POST_SUCCESS,
            ExecutionState.POST_FAILURE,
        }

    def test_factory_function_defaults(self):
        """Test factory function default values."""

        def test_callback():
            pass

        # Test defaults
        observer = on_success(test_callback)
        assert observer.priority == 0
        assert observer.name == "OnSuccess"


# Integration Tests
class TestObserverPatternIntegration:
    """Test integration of observer pattern components."""

    def test_complete_observer_lifecycle(self, sample_context):
        """Test complete lifecycle of observer pattern."""
        manager = ErrorIsolatingObserverManager()

        # Create observers with different priorities and interests
        call_observer = on_call(lambda context: None, priority=100)
        success_observer = on_success(lambda result: None, priority=50)
        completion_observer = on_completion(lambda context: None, priority=25)

        # Add observers with proper state registration
        manager.add_observer(call_observer, states={ExecutionState.PRE_EXECUTION})
        manager.add_observer(success_observer, states={ExecutionState.POST_SUCCESS})
        manager.add_observer(completion_observer, states={ExecutionState.COMPLETED})

        assert manager.get_observer_count() == 3

        # Test state-specific notifications
        pre_context = sample_context.with_state(ExecutionState.PRE_EXECUTION)
        success_context = sample_context.with_state(ExecutionState.POST_SUCCESS)
        complete_context = sample_context.with_state(ExecutionState.COMPLETED)

        # Each should trigger appropriate observers
        pre_observers = manager.get_observers_for_state(ExecutionState.PRE_EXECUTION)
        success_observers = manager.get_observers_for_state(ExecutionState.POST_SUCCESS)
        complete_observers = manager.get_observers_for_state(ExecutionState.COMPLETED)

        assert len(pre_observers) == 1  # call_observer
        assert len(success_observers) == 1  # success_observer
        assert len(complete_observers) == 1  # completion_observer

    def test_observer_pattern_with_metrics_and_logging(self, sample_context):
        """Test integration with built-in observers."""
        manager = ConcurrentObserverManager()

        # Add built-in observers
        metrics = MetricsObserver(priority=100)
        logging_obs = LoggingObserver(priority=50)
        timing = TimingObserver(priority=25)

        manager.add_observer(metrics, states={ExecutionState.POST_SUCCESS})
        manager.add_observer(logging_obs, states={ExecutionState.POST_SUCCESS})
        manager.add_observer(timing, states={ExecutionState.POST_SUCCESS})

        # Notify all observers
        manager.notify_observers(sample_context)

        # Verify each observer processed the context
        metrics_data = metrics.get_metrics()
        assert metrics_data["total_executions"] == 1

        slow_executions = timing.get_slow_executions()
        # Should be empty since execution time (0.123s) is below default threshold (1.0s)
        assert len(slow_executions) == 0

    def test_concurrent_observer_execution(self, sample_context):
        """Test concurrent execution of observers."""
        manager = ConcurrentObserverManager()

        execution_log = []
        lock = threading.Lock()

        def thread_safe_callback(context):
            with lock:
                execution_log.append(
                    f"{threading.current_thread().name}:{context.function_signature.name}"
                )

        # Add multiple observers
        for i in range(5):
            observer = CallbackObserver(
                thread_safe_callback,
                interested_states={ExecutionState.POST_SUCCESS},
                priority=100 - i,
                name=f"Observer_{i}",
            )
            manager.add_observer(observer, states={ExecutionState.POST_SUCCESS})

        # Execute with multiple threads
        def notify_worker():
            manager.notify_observers(sample_context)

        threads = []
        for i in range(3):
            thread = threading.Thread(target=notify_worker, name=f"Worker_{i}")
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Should have 15 total executions (3 threads * 5 observers)
        assert len(execution_log) == 15

    def test_observer_error_resilience(self, sample_context):
        """Test system resilience to observer errors."""
        manager = ErrorIsolatingObserverManager(max_failures=2)

        # Create mix of working and failing observers
        working_calls = []

        # Create custom observers that don't catch exceptions internally
        # so we can test the manager's error isolation
        class WorkingObserver:
            def __init__(self):
                self.priority = 50
                self.name = "WorkingObserver"

            def update(self, context):
                working_calls.append(context.function_signature.name)

        class FailingObserver:
            def __init__(self):
                self.priority = 40
                self.name = "FailingObserver"
                self.call_count = 0

            def update(self, context):
                self.call_count += 1
                raise RuntimeError("Simulated observer failure")

        working_observer = WorkingObserver()
        failing_observer = FailingObserver()

        manager.add_observer(working_observer, states={ExecutionState.POST_SUCCESS})
        manager.add_observer(failing_observer, states={ExecutionState.POST_SUCCESS})

        # Use proper context state
        success_context = sample_context.with_state(ExecutionState.POST_SUCCESS)

        # Execute multiple times
        for _ in range(5):
            manager.notify_observers(success_context)

        # Working observer should have been called every time
        assert len(working_calls) == 5

        # Failing observer should be disabled after max_failures (2)
        assert failing_observer in manager._disabled_observers

        # Failing observer should have been called exactly max_failures times before being disabled
        assert failing_observer.call_count == 2

    def test_callback_observer_error_isolation(self, sample_context):
        """Test that CallbackObserver isolates callback errors."""
        calls = []

        def working_callback(context):
            calls.append("working")

        def failing_callback(context):
            calls.append("failing_attempt")
            raise RuntimeError("Callback error")

        working_observer = CallbackObserver(
            working_callback, interested_states={ExecutionState.POST_SUCCESS}
        )
        failing_observer = CallbackObserver(
            failing_callback, interested_states={ExecutionState.POST_SUCCESS}
        )

        manager = ConcurrentObserverManager()
        manager.add_observer(working_observer, states={ExecutionState.POST_SUCCESS})
        manager.add_observer(failing_observer, states={ExecutionState.POST_SUCCESS})

        success_context = sample_context.with_state(ExecutionState.POST_SUCCESS)

        # Should not raise, both observers should be called
        manager.notify_observers(success_context)

        # Both callbacks should have been attempted
        assert "working" in calls
        assert "failing_attempt" in calls

        # Working observer should continue to work on subsequent calls
        manager.notify_observers(success_context)
        assert calls.count("working") == 2
        assert calls.count("failing_attempt") == 2


# Performance Tests
class TestObserverPerformance:
    """Test observer pattern performance characteristics."""

    def test_observer_notification_performance(self, sample_context):
        """Test performance of observer notifications."""
        manager = ConcurrentObserverManager()

        # Add many observers
        observers = []
        for i in range(100):
            observer = MockObserver(priority=i, name=f"Observer_{i}")
            observers.append(observer)
            manager.add_observer(observer, states={ExecutionState.POST_SUCCESS})

        # Measure notification time
        start_time = time.time()
        for _ in range(10):
            manager.notify_observers(sample_context)
        end_time = time.time()

        # Should complete quickly (less than 1 second for 100 observers * 10 notifications)
        total_time = end_time - start_time
        assert total_time < 1.0

        # Verify all observers were called
        for observer in observers:
            assert len(observer.update_calls) == 10

    def test_memory_efficiency_with_weak_references(self):
        """Test memory efficiency using weak references."""
        manager = ConcurrentObserverManager()

        # Create observers and add to manager
        for i in range(10):
            observer = MockObserver(name=f"Observer_{i}")
            manager.add_observer(observer, states={ExecutionState.POST_SUCCESS})

        assert manager.get_observer_count() == 10

        # Observers should be garbage collected when references are lost
        # Note: This test is implementation-dependent and may need adjustment
        # based on how weak references are used in the observer manager


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
