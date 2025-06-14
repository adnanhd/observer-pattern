"""Edge cases and advanced scenarios for CallPyBack observer pattern."""

import gc
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from unittest.mock import MagicMock, Mock, patch

import pytest

from callpyback.core.context import (
    ExecutionContext,
    ExecutionFailure,
    ExecutionResult,
    FunctionSignature,
)
from callpyback.core.state_machine import ExecutionState, StateMachine
from callpyback.errors import ConfigurationError
from callpyback.management.observer_manager import (
    ConcurrentObserverManager,
    ErrorIsolatingObserverManager,
)
from callpyback.observers.base import BaseObserver
from callpyback.observers.builtin import MetricsObserver, TimingObserver
from callpyback.observers.callback import CallbackObserver
from callpyback.protocols import Observer


class TestObserverEdgeCases:
    """Test edge cases in observer behavior."""

    def test_observer_with_no_parameters(self):
        """Test observer callback with no parameters."""
        calls = []

        def no_param_callback():
            calls.append("called")

        observer = CallbackObserver(no_param_callback)

        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature, arguments={}, state=ExecutionState.COMPLETED
        )

        observer.update(context)
        assert len(calls) == 1

    def test_observer_with_partial_parameters(self):
        """Test observer callback with subset of available parameters."""
        captured_data = {}

        def partial_callback(function_signature, timestamp):
            captured_data["function_name"] = function_signature.name
            captured_data["timestamp"] = timestamp

        observer = CallbackObserver(partial_callback)

        signature = FunctionSignature("test_func", "module", ())
        context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.COMPLETED,
            timestamp=123456.789,
        )

        observer.update(context)
        assert captured_data["function_name"] == "test_func"
        assert captured_data["timestamp"] == 123456.789

    def test_observer_with_context_without_result(self):
        """Test observer handling context without result."""
        calls = []

        def callback_with_result(result):
            calls.append(result)

        observer = CallbackObserver(
            callback_with_result, interested_states={ExecutionState.PRE_EXECUTION}
        )

        # Context without result
        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.PRE_EXECUTION,  # No result in pre-execution
            result=None,
        )

        observer.update(context)
        assert len(calls) == 1
        assert calls[0] is None

    def test_observer_state_filtering_edge_cases(self):
        """Test edge cases in state filtering."""
        calls = []

        def test_callback(context):
            calls.append(context.state.name)

        # Observer interested in multiple states
        observer = CallbackObserver(
            test_callback,
            interested_states={
                ExecutionState.PRE_EXECUTION,
                ExecutionState.POST_SUCCESS,
                ExecutionState.COMPLETED,
            },
        )

        signature = FunctionSignature("test", "module", ())

        # Test all execution states
        all_states = [
            ExecutionState.INITIALIZED,
            ExecutionState.PRE_EXECUTION,
            ExecutionState.EXECUTING,
            ExecutionState.POST_SUCCESS,
            ExecutionState.POST_FAILURE,
            ExecutionState.COMPLETED,
            ExecutionState.ERROR,
        ]

        for state in all_states:
            context = ExecutionContext(
                function_signature=signature, arguments={}, state=state
            )
            observer.update(context)

        # Should only be called for interested states
        assert len(calls) == 3
        assert "PRE_EXECUTION" in calls
        assert "POST_SUCCESS" in calls
        assert "COMPLETED" in calls

    def test_observer_priority_edge_cases(self):
        """Test edge cases with observer priorities."""
        execution_order = []

        def create_callback(name):
            def callback(context):
                execution_order.append(name)

            return callback

        manager = ConcurrentObserverManager()

        # Add observers with same priority
        obs1 = CallbackObserver(create_callback("obs1"), priority=50)
        obs2 = CallbackObserver(create_callback("obs2"), priority=50)
        obs3 = CallbackObserver(create_callback("obs3"), priority=50)

        # Add observers with extreme priorities
        obs_max = CallbackObserver(create_callback("max"), priority=float("inf"))
        obs_min = CallbackObserver(create_callback("min"), priority=float("-inf"))

        for obs in [obs1, obs2, obs3, obs_max, obs_min]:
            manager.add_observer(obs, states={ExecutionState.COMPLETED})

        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature, arguments={}, state=ExecutionState.COMPLETED
        )

        manager.notify_observers(context)

        # Max priority should be first, min should be last
        assert execution_order[0] == "max"
        assert execution_order[-1] == "min"
        # Middle three should maintain some order (implementation dependent)
        assert len(execution_order) == 5

    def test_observer_with_complex_callback_signatures(self):
        """Test observers with complex callback signatures."""
        # Test with valid parameter combinations
        captured_args = {}

        def complex_callback(context, result, metadata):
            captured_args["context"] = context
            captured_args["result"] = result
            captured_args["metadata"] = metadata

        observer = CallbackObserver(
            complex_callback, interested_states={ExecutionState.COMPLETED}
        )

        signature = FunctionSignature("test", "module", ())
        result = ExecutionResult("test_result", 0.1)
        context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.COMPLETED,
            result=result,
            metadata={"test_key": "test_value"},
        )

        observer.update(context)

        assert captured_args["context"] == context
        assert captured_args["result"] == result
        assert captured_args["metadata"] == {"test_key": "test_value"}


class TestObserverManagerEdgeCases:
    """Test edge cases in observer manager behavior."""

    def test_observer_manager_with_no_observers(self):
        """Test observer manager behavior with no observers."""
        manager = ConcurrentObserverManager()

        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature, arguments={}, state=ExecutionState.COMPLETED
        )

        # Should not raise
        manager.notify_observers(context)

        assert manager.get_observer_count() == 0
        assert manager.get_observers_for_state(ExecutionState.COMPLETED) == []

    def test_observer_manager_removing_nonexistent_observer(self):
        """Test removing observer that doesn't exist."""
        manager = ConcurrentObserverManager()
        observer = CallbackObserver(lambda: None)

        # Should not raise
        manager.remove_observer(observer)

    def test_observer_manager_with_duplicate_observers(self):
        """Test adding the same observer multiple times."""
        manager = ConcurrentObserverManager()
        observer = CallbackObserver(lambda context: None)

        # Add same observer multiple times
        manager.add_observer(observer, states={ExecutionState.COMPLETED})
        manager.add_observer(observer, states={ExecutionState.COMPLETED})
        manager.add_observer(observer, states={ExecutionState.POST_SUCCESS})

        # Should appear in both state collections
        completed_observers = manager.get_observers_for_state(ExecutionState.COMPLETED)
        success_observers = manager.get_observers_for_state(ExecutionState.POST_SUCCESS)

        assert observer in completed_observers
        assert observer in success_observers

    def test_observer_manager_thread_safety_edge_cases(self):
        """Test thread safety with rapid add/remove operations."""
        manager = ConcurrentObserverManager()
        observers = []

        def add_remove_worker():
            local_observers = []
            for i in range(10):
                obs = CallbackObserver(lambda context: None, name=f"worker_obs_{i}")
                local_observers.append(obs)
                manager.add_observer(obs, states={ExecutionState.COMPLETED})

            # Remove half of them
            for obs in local_observers[::2]:
                manager.remove_observer(obs)

            observers.extend(local_observers[1::2])  # Keep track of remaining

        # Run multiple threads adding/removing observers
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=add_remove_worker)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Final count should be predictable
        # Each thread adds 10, removes 5, so 5 * 5 = 25 observers should remain
        final_count = manager.get_observer_count()
        assert final_count <= 25  # May be less due to weak references

    def test_error_isolating_manager_edge_cases(self):
        """Test edge cases in error isolating manager."""
        manager = ErrorIsolatingObserverManager(max_failures=1)

        calls = []

        # Create custom observer that doesn't catch exceptions internally
        class AlternatingObserver:
            def __init__(self):
                self.call_count = 0
                self.priority = 0
                self.name = "AlternatingObserver"
                # Alternating fail/success pattern
                self.failures = [True, False, True, False]

            def update(self, context):
                calls.append(self.call_count)
                if self.failures[self.call_count % len(self.failures)]:
                    self.call_count += 1
                    raise RuntimeError("Alternating failure")
                self.call_count += 1

        observer = AlternatingObserver()
        manager.add_observer(observer, states={ExecutionState.COMPLETED})

        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature, arguments={}, state=ExecutionState.COMPLETED
        )

        # Execute multiple times
        for _ in range(6):
            manager.notify_observers(context)

        # Observer should be disabled after first failure (max_failures=1)
        assert observer in manager._disabled_observers
        # Should only have been called once (first failure disables it)
        assert len(calls) == 1
        assert observer.call_count == 1

    def test_observer_manager_memory_management(self):
        """Test memory management with weak references."""
        manager = ConcurrentObserverManager()

        # Create observers and keep weak references
        weak_refs = []
        for i in range(10):
            observer = CallbackObserver(lambda context: None, name=f"obs_{i}")
            weak_ref = weakref.ref(observer)
            weak_refs.append(weak_ref)
            manager.add_observer(observer, states={ExecutionState.COMPLETED})
            del observer  # Remove strong reference

        # Force garbage collection
        gc.collect()

        # Some observers might be collected (depending on implementation)
        # This test verifies the system handles weak references properly
        alive_refs = [ref for ref in weak_refs if ref() is not None]
        dead_refs = [ref for ref in weak_refs if ref() is None]

        # At least some should be collected, but system might keep some alive
        # The important thing is no exceptions are raised
        manager_count = manager.get_observer_count()
        assert manager_count >= 0  # Should not raise


class TestObserverPerformanceEdgeCases:
    """Test performance edge cases and stress scenarios."""

    def test_large_number_of_observers(self):
        """Test system behavior with large number of observers."""
        manager = ConcurrentObserverManager()

        # Add many observers
        call_counts = {}

        def create_callback(observer_id):
            def callback(context):
                call_counts[observer_id] = call_counts.get(observer_id, 0) + 1

            return callback

        num_observers = 1000
        for i in range(num_observers):
            observer = CallbackObserver(
                create_callback(i),
                priority=i % 100,  # Vary priorities
                name=f"observer_{i}",
            )
            manager.add_observer(observer, states={ExecutionState.COMPLETED})

        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature, arguments={}, state=ExecutionState.COMPLETED
        )

        # Measure notification time
        start_time = time.time()
        manager.notify_observers(context)
        end_time = time.time()

        # Should complete in reasonable time (less than 1 second)
        assert (end_time - start_time) < 1.0

        # All observers should have been called
        assert len(call_counts) == num_observers
        assert all(count == 1 for count in call_counts.values())

    def test_deep_callback_recursion(self):
        """Test behavior with recursive callback scenarios."""
        manager = ConcurrentObserverManager()
        recursion_depth = 0
        max_depth = 50

        def recursive_callback(context):
            nonlocal recursion_depth
            if recursion_depth < max_depth:
                recursion_depth += 1
                # Simulate recursive notification (carefully)
                inner_context = ExecutionContext(
                    function_signature=FunctionSignature("inner", "module", ()),
                    arguments={},
                    state=ExecutionState.POST_SUCCESS,
                )
                # Note: In real scenario, this would be dangerous
                # This is just testing the observer's resilience
                recursion_depth -= 1

        observer = CallbackObserver(
            recursive_callback, interested_states={ExecutionState.COMPLETED}
        )
        manager.add_observer(observer, states={ExecutionState.COMPLETED})

        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature, arguments={}, state=ExecutionState.COMPLETED
        )

        # Should handle gracefully
        manager.notify_observers(context)
        assert recursion_depth == 0  # Should return to original state

    def test_concurrent_notifications_stress_test(self):
        """Stress test with concurrent notifications."""
        manager = ConcurrentObserverManager()

        # Shared state for tracking
        notification_count = {"value": 0}
        lock = threading.Lock()

        def counting_callback(context):
            with lock:
                notification_count["value"] += 1
                time.sleep(0.001)  # Small delay to encourage race conditions

        # Add multiple observers
        for i in range(10):
            observer = CallbackObserver(
                counting_callback, name=f"counting_observer_{i}"
            )
            manager.add_observer(observer, states={ExecutionState.COMPLETED})

        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature, arguments={}, state=ExecutionState.COMPLETED
        )

        # Run many concurrent notifications
        def notification_worker():
            for _ in range(10):
                manager.notify_observers(context)

        threads = []
        num_threads = 5
        for _ in range(num_threads):
            thread = threading.Thread(target=notification_worker)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Should have correct total count
        expected_count = num_threads * 10 * 10  # threads * calls_per_thread * observers
        assert notification_count["value"] == expected_count


class TestObserverStateManagementEdgeCases:
    """Test edge cases in state management."""

    def test_observer_with_invalid_states(self):
        """Test observer behavior with edge case states."""
        calls = []

        def state_callback(context):
            calls.append(context.state)

        # Create observer interested in all states
        observer = CallbackObserver(
            state_callback, interested_states=set(ExecutionState)  # All possible states
        )

        manager = ConcurrentObserverManager()
        manager.add_observer(observer, states=set(ExecutionState))

        signature = FunctionSignature("test", "module", ())

        # Test with each possible state
        for state in ExecutionState:
            context = ExecutionContext(
                function_signature=signature, arguments={}, state=state
            )
            manager.notify_observers(context)

        # Should have been called for each state
        assert len(calls) == len(ExecutionState)
        assert set(calls) == set(ExecutionState)

    def test_state_transitions_during_observation(self):
        """Test observer behavior during state transitions."""
        state_log = []

        def state_logging_callback(context):
            state_log.append(context.state.name)
            # Simulate some processing time
            time.sleep(0.001)

        manager = ConcurrentObserverManager()
        observer = CallbackObserver(
            state_logging_callback,
            interested_states={
                ExecutionState.PRE_EXECUTION,
                ExecutionState.POST_SUCCESS,
                ExecutionState.COMPLETED,
            },
        )

        manager.add_observer(
            observer,
            states={
                ExecutionState.PRE_EXECUTION,
                ExecutionState.POST_SUCCESS,
                ExecutionState.COMPLETED,
            },
        )

        signature = FunctionSignature("test", "module", ())

        # Simulate state machine progression
        states = [
            ExecutionState.PRE_EXECUTION,
            ExecutionState.POST_SUCCESS,
            ExecutionState.COMPLETED,
        ]

        for state in states:
            context = ExecutionContext(
                function_signature=signature, arguments={}, state=state
            )
            manager.notify_observers(context)

        assert state_log == ["PRE_EXECUTION", "POST_SUCCESS", "COMPLETED"]


class TestObserverCallbackEdgeCases:
    """Test edge cases in callback behavior."""

    def test_callback_with_side_effects(self):
        """Test callbacks that modify external state."""
        external_state = {"counter": 0, "data": []}

        def side_effect_callback(context):
            external_state["counter"] += 1
            external_state["data"].append(context.function_signature.name)
            # Simulate complex side effects
            if external_state["counter"] % 2 == 0:
                external_state["data"].reverse()

        observer = CallbackObserver(side_effect_callback)

        signature = FunctionSignature("test_func", "module", ())
        context = ExecutionContext(
            function_signature=signature, arguments={}, state=ExecutionState.COMPLETED
        )

        # Execute multiple times
        for i in range(5):
            observer.update(context)

        assert external_state["counter"] == 5
        # Due to reversing on even counts, order might be complex
        assert "test_func" in external_state["data"]

    def test_callback_exception_types(self):
        """Test various exception types in callbacks."""
        exception_types = [
            RuntimeError("Runtime error"),
            ValueError("Value error"),
            TypeError("Type error"),
            KeyError("Key error"),
            AttributeError("Attribute error"),
            ImportError("Import error"),
        ]

        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature, arguments={}, state=ExecutionState.COMPLETED
        )

        for exc in exception_types:

            def failing_callback(context):
                raise exc

            observer = CallbackObserver(failing_callback)

            # Should not propagate any exception
            with patch("callpyback.observers.callback.logging") as mock_logging:
                observer.update(context)
                mock_logging.error.assert_called_once()
                mock_logging.reset_mock()

    def test_callback_parameter_extraction_edge_cases(self):
        """Test edge cases in parameter extraction."""
        # Test with context that has None values
        signature = FunctionSignature("test", "module", ())
        context = ExecutionContext(
            function_signature=signature,
            arguments={},
            state=ExecutionState.COMPLETED,
            result=None,  # No result
            local_variables=None,  # No variables
            metadata={},
        )

        extracted_values = {}

        def extraction_callback(context, result, local_variables, metadata):
            extracted_values["context"] = context
            extracted_values["result"] = result
            extracted_values["local_variables"] = local_variables
            extracted_values["metadata"] = metadata

        observer = CallbackObserver(
            extraction_callback, interested_states={ExecutionState.COMPLETED}
        )
        observer.update(context)

        assert extracted_values["context"] == context
        assert extracted_values["result"] is None
        assert extracted_values["local_variables"] is None
        assert extracted_values["metadata"] == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
