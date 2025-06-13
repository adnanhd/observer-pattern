"""Advanced usage examples for CallPyBack."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any

from callpyback import CallPyBack, ExecutionContext, on_call
from callpyback.factories import on_success
from callpyback.observers.base import BaseObserver
from callpyback.observers.builtin import MetricsObserver
from callpyback.core.state_machine import ExecutionState


class DatabaseAuditObserver(BaseObserver):
    """Custom observer for database auditing."""

    def __init__(self, connection=None, priority=75):
        super().__init__(priority, "DatabaseAudit")
        self.connection = connection
        self.audit_log = []  # Mock database

    def update(self, context: ExecutionContext) -> None:
        """Log execution to audit database."""
        if context.state == ExecutionState.COMPLETED:
            audit_entry = {
                "function_name": context.function_signature.name,
                "timestamp": context.timestamp,
                "success": context.is_successful,
                "execution_time": (
                    context.result.execution_time
                    if context.result and hasattr(context.result, "execution_time")
                    else None
                ),
                "arguments": str(context.arguments),
            }
            self.audit_log.append(audit_entry)
            print(f"Audit: {audit_entry}")


class PerformanceProfiler(BaseObserver):
    """Advanced performance profiling observer."""

    def __init__(self, percentile_threshold=95, priority=50):
        super().__init__(priority, "PerformanceProfiler")
        self.execution_times = {}
        self.percentile_threshold = percentile_threshold

    def update(self, context: ExecutionContext) -> None:
        """Track performance and alert on anomalies."""
        if (
            context.state == ExecutionState.POST_SUCCESS
            and context.result
            and hasattr(context.result, "execution_time")
        ):

            func_name = context.function_signature.name
            exec_time = context.result.execution_time

            if func_name not in self.execution_times:
                self.execution_times[func_name] = []

            self.execution_times[func_name].append(exec_time)

            # Check for performance anomalies
            if len(self.execution_times[func_name]) >= 10:
                times = self.execution_times[func_name]
                threshold = self._calculate_percentile(times, self.percentile_threshold)

                if exec_time > threshold:
                    print(
                        f"🐌 PERFORMANCE ALERT: {func_name} took {exec_time:.3f}s "
                        f"(>{self.percentile_threshold}th percentile: {threshold:.3f}s)"
                    )

    def _calculate_percentile(self, values, percentile):
        """Calculate percentile value."""
        sorted_values = sorted(values)
        index = int((percentile / 100) * len(sorted_values))
        return sorted_values[min(index, len(sorted_values) - 1)]


def custom_observers_example():
    """Example using custom observers."""

    # Mock database connection
    mock_db = None

    # Create custom observers
    audit_observer = DatabaseAuditObserver(mock_db, priority=100)
    performance_observer = PerformanceProfiler(percentile_threshold=90)

    @CallPyBack(observers=[audit_observer, performance_observer])
    def critical_business_function(user_id, action):
        """Critical function that needs auditing and performance monitoring."""
        import random

        # Simulate variable processing time
        processing_time = random.uniform(0.01, 0.2)
        time.sleep(processing_time)

        return f"User {user_id} performed {action} successfully"

    print("=== Custom observers example ===")

    # Execute function multiple times
    for i in range(15):
        result = critical_business_function(f"user_{i}", "login")
        print(f"Execution {i}: {result}")

    # Show audit log
    print(f"\nAudit entries: {len(audit_observer.audit_log)}")
    for entry in audit_observer.audit_log[-3:]:  # Show last 3
        print(f"  {entry}")


def thread_safety_example():
    """Example demonstrating thread safety."""

    # Shared metrics observer
    metrics = MetricsObserver()

    # Thread-safe counter
    counter = {"value": 0}
    lock = threading.Lock()

    def thread_safe_increment(context):
        with lock:
            counter["value"] += 1
            print(
                f"Thread {threading.current_thread().name}: "
                f"Call #{counter['value']} - {context.function_signature.name}"
            )

    @CallPyBack(
        observers=[metrics, on_call(thread_safe_increment)],
        enable_async_observers=True,  # Enable async observer execution
    )
    def concurrent_function(thread_id, work_amount):
        """Function designed for concurrent execution."""
        import random

        # Simulate work
        work_time = random.uniform(0.01, 0.05)
        time.sleep(work_time)

        return f"Thread {thread_id} completed work: {work_amount}"

    print("=== Thread safety example ===")

    # Execute concurrently
    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="Worker") as executor:
        futures = []

        for i in range(10):
            future = executor.submit(concurrent_function, i, f"task_{i}")
            futures.append(future)

        # Collect results
        results = []
        for future in futures:
            try:
                result = future.result(timeout=5.0)
                results.append(result)
            except Exception as e:
                print(f"Task failed: {e}")

    print(f"\nCompleted {len(results)} concurrent executions")
    print(f"Total function calls: {counter['value']}")

    # Show metrics
    metrics_data = metrics.get_metrics()
    print(f"Metrics: {metrics_data['total_executions']} executions recorded")


def variable_capture_example():
    """Advanced variable capture example."""

    captured_data = []

    def analyze_variables(local_variables):
        """Analyze captured variables for insights."""
        if local_variables:
            analysis = {
                "variable_count": len(
                    [
                        v
                        for v in local_variables.values()
                        if not str(v).startswith("<Variable")
                    ]
                ),
                "numeric_vars": sum(
                    1 for v in local_variables.values() if isinstance(v, (int, float))
                ),
                "string_vars": sum(
                    1 for v in local_variables.values() if isinstance(v, str)
                ),
                "variables": local_variables,
            }
            captured_data.append(analysis)
            print(f"Variable analysis: {analysis['variable_count']} vars captured")

    @CallPyBack(
        observers=[on_success(analyze_variables)],
        variable_names=["input_data", "processed", "result_type", "final_output"],
    )
    def data_processing_pipeline(data, transform_type="upper"):
        """Complex data processing with multiple variables."""
        input_data = data

        if transform_type == "upper":
            processed = data.upper() if isinstance(data, str) else str(data).upper()
        elif transform_type == "reverse":
            processed = data[::-1] if isinstance(data, str) else str(data)[::-1]
        else:
            processed = data

        result_type = type(processed).__name__
        final_output = f"[{result_type}] {processed}"

        return final_output

    print("=== Variable capture example ===")

    # Test different transformations
    test_cases = [
        ("hello world", "upper"),
        ("python", "reverse"),
        (12345, "upper"),
        ("test", "unknown"),
    ]

    for data, transform in test_cases:
        result = data_processing_pipeline(data, transform)
        print(f"Input: {data}, Transform: {transform} -> {result}")

    print(f"\nCaptured {len(captured_data)} variable snapshots")
    for i, analysis in enumerate(captured_data):
        print(
            f"Snapshot {i}: {analysis['variable_count']} variables "
            f"({analysis['numeric_vars']} numeric, {analysis['string_vars']} string)"
        )


def state_monitoring_example():
    """Example monitoring state transitions."""

    state_log = []

    def log_state_transitions(context):
        """Log all state transitions."""
        state_entry = {
            "function": context.function_signature.name,
            "state": context.state.name,
            "timestamp": context.timestamp,
            "has_result": context.result is not None,
        }
        state_log.append(state_entry)
        print(f"State: {context.state.name} - {context.function_signature.name}")

    # Create observer that monitors all states
    from callpyback.observers.callback import CallbackObserver

    all_states_observer = CallbackObserver(
        log_state_transitions,
        interested_states={
            ExecutionState.PRE_EXECUTION,
            ExecutionState.EXECUTING,
            ExecutionState.POST_SUCCESS,
            ExecutionState.POST_FAILURE,
            ExecutionState.COMPLETED,
        },
    )

    @CallPyBack(observers=[all_states_observer])
    def stateful_function(should_fail=False):
        """Function to demonstrate state transitions."""
        if should_fail:
            raise ValueError("Intentional failure")
        return "success"

    print("=== State monitoring example ===")

    # Test successful execution
    print("Successful execution:")
    result1 = stateful_function(False)
    print(f"Result: {result1}\n")

    # Test failed execution
    print("Failed execution:")
    result2 = stateful_function(True)
    print(f"Result: {result2}\n")

    print("State transition log:")
    for entry in state_log:
        print(
            f"  {entry['state']}: {entry['function']} "
            f"(result: {entry['has_result']})"
        )


if __name__ == "__main__":
    custom_observers_example()
    print("\n" + "=" * 60 + "\n")
    thread_safety_example()
    print("\n" + "=" * 60 + "\n")
    variable_capture_example()
    print("\n" + "=" * 60 + "\n")
    state_monitoring_example()
