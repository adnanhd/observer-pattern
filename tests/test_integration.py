"""Fixed integration tests for CallPyBack."""

import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from callpyback.core.decorator import CallPyBack
from callpyback.observers.builtin import (
    LoggingObserver,
    MetricsObserver,
    TimingObserver,
)
from callpyback.factories import on_call, on_success, on_failure, on_completion
from callpyback.core.state_machine import ExecutionState


class TestIntegration:
    """Integration tests for complete functionality."""

    def test_complex_scenario(self):
        """Test complex real-world scenario."""
        # Set up comprehensive monitoring
        metrics = MetricsObserver()
        logger = LoggingObserver()

        call_log = []
        success_log = []
        failure_log = []

        @CallPyBack(
            observers=[
                metrics,
                logger,
                on_call(
                    lambda context: call_log.append(context.function_signature.name)
                ),
                on_success(lambda result: success_log.append(result.value)),
                on_failure(lambda result: failure_log.append(str(result.exception))),
            ],
            variable_names=["processing_step", "intermediate_result"],
            exception_classes=(ValueError, TypeError),
            default_return="default",
        )
        def data_processor(data, should_fail=False):
            processing_step = "validation"

            if should_fail:
                raise ValueError("Processing failed")

            processing_step = "transformation"
            intermediate_result = data * 2

            processing_step = "finalization"
            return f"processed: {intermediate_result}"

        # Test successful execution
        result1 = data_processor("test")
        assert result1 == "processed: testtest"
        assert len(call_log) == 1
        assert len(success_log) == 1

        # Test failure
        result2 = data_processor("test", should_fail=True)
        assert result2 == "default"
        # Note: Changed expectation from 1 to 2 since we had one call already
        assert len(call_log) == 2  # Should have 2 calls total now
        assert len(failure_log) == 1

        # Check metrics
        metrics_data = metrics.get_metrics()
        assert metrics_data["function_stats"]["data_processor"]["calls"] == 2
        assert metrics_data["function_stats"]["data_processor"]["successes"] == 1
        assert metrics_data["function_stats"]["data_processor"]["failures"] == 1

    def test_concurrent_execution(self):
        """Test thread safety with concurrent execution."""
        metrics = MetricsObserver()
        call_count = {"value": 0}
        lock = threading.Lock()

        def thread_safe_counter(context):
            with lock:
                call_count["value"] += 1

        @CallPyBack(observers=[metrics, on_call(thread_safe_counter)])
        def concurrent_function(x):
            time.sleep(0.01)  # Small delay to encourage race conditions
            return x * 2

        # Execute concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(concurrent_function, i) for i in range(20)]
            results = [f.result() for f in futures]

        # Verify all executions completed
        assert len(results) == 20
        assert all(isinstance(r, int) for r in results)
        assert call_count["value"] == 20

        # Verify metrics
        metrics_data = metrics.get_metrics()
        assert metrics_data["function_stats"]["concurrent_function"]["calls"] == 20

    def test_performance_monitoring(self):
        """Test performance monitoring capabilities."""
        timing_observer = TimingObserver(threshold=0.05)  # 50ms threshold

        @CallPyBack(observers=[timing_observer])
        def fast_function():
            return "fast"

        @CallPyBack(observers=[timing_observer])
        def slow_function():
            time.sleep(0.1)  # 100ms - above threshold
            return "slow"

        # Execute functions
        fast_function()
        slow_function()

        # Check slow executions
        slow_executions = timing_observer.get_slow_executions()
        assert len(slow_executions) == 1
        assert slow_executions[0]["function_name"] == "slow_function"
        assert slow_executions[0]["execution_time"] >= 0.1
