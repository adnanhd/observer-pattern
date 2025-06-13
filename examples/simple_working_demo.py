"""Simple working CallPyBack examples that actually work."""

from callpyback import CallPyBack, on_call, on_success, on_failure, on_completion
from callpyback.observers.builtin import LoggingObserver, MetricsObserver


def basic_working_example():
    """Basic example that works without complex error chains."""
    print("=== Basic Working Example ===")

    # Simple callbacks
    def log_call(context):
        print(f"📞 Calling: {context.function_signature.name}")

    def log_success(result):
        print(f"✅ Success: {result.value}")

    def log_failure(result):
        print(f"❌ Failed: {result.exception}")

    @CallPyBack(
        observers=[on_call(log_call), on_success(log_success), on_failure(log_failure)],
        default_return="error_handled",
    )
    def divide(a, b):
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b

    # Test success
    print("Testing successful division:")
    result = divide(10, 2)
    print(f"Result: {result}\n")

    # Test error handling
    print("Testing error handling:")
    result = divide(10, 0)
    print(f"Result: {result}\n")


def variable_extraction_example():
    """Variable extraction example."""
    print("=== Variable Extraction Example ===")

    extracted_data = []

    def capture_variables(local_variables):
        extracted_data.append(local_variables)
        print(f"📋 Captured variables: {local_variables}")

    @CallPyBack(
        observers=[on_completion(capture_variables)],
        variable_names=["step1", "step2", "final"],
    )
    def multi_step_calculation(x, y):
        step1 = x * 2
        step2 = y + 5
        final = step1 + step2
        return final

    result = multi_step_calculation(3, 4)
    print(f"✅ Final result: {result}")
    print(f"📊 Total variable captures: {len(extracted_data)}\n")


def metrics_example():
    """Metrics collection example."""
    print("=== Metrics Example ===")

    metrics_observer = MetricsObserver()

    @CallPyBack(observers=[metrics_observer])
    def api_endpoint(data):
        if data == "error":
            raise ValueError("Bad data")
        return f"Processed: {data}"

    # Execute multiple times
    test_data = ["hello", "world", "error", "test", "error"]

    for data in test_data:
        try:
            result = api_endpoint(data)
            print(f"📤 {data} -> {result}")
        except:
            print(f"📤 {data} -> ERROR")

    # Show metrics
    metrics = metrics_observer.get_metrics()
    print(f"\n📊 Metrics Summary:")
    print(f"   Total executions: {metrics['total_executions']}")
    print(f"   Function stats: {metrics['function_stats']}")
    print()


def error_handling_example():
    """Different error handling scenarios."""
    print("=== Error Handling Scenarios ===")

    # Scenario 1: Handle specific errors
    @CallPyBack(
        observers=[on_failure(lambda r: print(f"🚨 Caught: {r.exception}"))],
        exception_classes=(ValueError, TypeError),  # Only catch these
        default_return="handled",
    )
    def picky_function(error_type):
        if error_type == "value":
            raise ValueError("Value error")
        elif error_type == "type":
            raise TypeError("Type error")
        elif error_type == "runtime":
            raise RuntimeError("Runtime error")  # Won't be caught
        else:
            return f"Success: {error_type}"

    test_cases = ["success", "value", "type", "runtime"]

    for case in test_cases:
        try:
            result = picky_function(case)
            print(f"🎯 {case}: {result}")
        except Exception as e:
            print(f"🎯 {case}: UNCAUGHT - {e}")

    print()


def observer_priorities_example():
    """Observer execution order based on priorities."""
    print("=== Observer Priorities Example ===")

    execution_order = []

    def high_priority(context):
        execution_order.append("HIGH")
        print("🔴 High priority observer")

    def medium_priority(context):
        execution_order.append("MEDIUM")
        print("🟡 Medium priority observer")

    def low_priority(context):
        execution_order.append("LOW")
        print("🟢 Low priority observer")

    @CallPyBack(
        observers=[
            on_success(low_priority, priority=1),  # Low priority
            on_success(high_priority, priority=100),  # High priority
            on_success(medium_priority, priority=50),  # Medium priority
        ]
    )
    def ordered_function():
        return "done"

    print("Observers should execute in order: HIGH -> MEDIUM -> LOW")
    result = ordered_function()
    print(f"✅ Function result: {result}")
    print(f"📋 Actual execution order: {' -> '.join(execution_order)}\n")


def custom_observer_example():
    """Custom observer implementation."""
    print("=== Custom Observer Example ===")

    from callpyback.observers.base import BaseObserver
    from callpyback.core.state_machine import ExecutionState

    class CustomAuditObserver(BaseObserver):
        def __init__(self):
            super().__init__(priority=75, name="CustomAudit")
            self.audit_log = []

        def update(self, context):
            if context.state == ExecutionState.COMPLETED:
                entry = {
                    "function": context.function_signature.name,
                    "success": context.is_successful,
                    "timestamp": context.timestamp,
                }
                self.audit_log.append(entry)
                print(f"📝 Audit: {entry}")

    audit = CustomAuditObserver()

    @CallPyBack(observers=[audit])
    def audited_function(action):
        if action == "fail":
            raise ValueError("Deliberate failure")
        return f"Action: {action}"

    # Test the audited function
    test_actions = ["login", "fail", "logout"]

    for action in test_actions:
        try:
            result = audited_function(action)
            print(f"🎬 {action}: {result}")
        except:
            print(f"🎬 {action}: FAILED")

    print(f"\n📋 Audit log contains {len(audit.audit_log)} entries\n")


def performance_monitoring_example():
    """Performance monitoring with timing."""
    print("=== Performance Monitoring Example ===")

    import time
    from callpyback.observers.builtin import TimingObserver

    timing_observer = TimingObserver(threshold=0.1)  # 100ms threshold

    @CallPyBack(observers=[timing_observer])
    def performance_function(delay):
        time.sleep(delay)
        return f"Slept for {delay}s"

    print("Testing with different delays (threshold: 0.1s):")

    delays = [0.05, 0.15, 0.08, 0.2]  # Some above, some below threshold

    for delay in delays:
        result = performance_function(delay)
        print(f"⏱️  {delay}s: {result}")

    slow_executions = timing_observer.get_slow_executions()
    print(f"\n🐌 Detected {len(slow_executions)} slow executions")
    for execution in slow_executions:
        print(f"   - {execution['function_name']}: {execution['execution_time']:.3f}s")

    print()


if __name__ == "__main__":
    basic_working_example()
    variable_extraction_example()
    metrics_example()
    error_handling_example()
    observer_priorities_example()
    custom_observer_example()
    performance_monitoring_example()

    print("🎉 All examples completed successfully!")
