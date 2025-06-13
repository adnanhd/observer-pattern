from typing import ValuesView

"""Basic usage examples for CallPyBack."""

from callpyback import CallPyBack, on_call, on_success, on_failure
from callpyback.observers.builtin import LoggingObserver, MetricsObserver


def basic_example():
    """Basic callback usage."""

    def log_call(context):
        print(f"Calling {context.function_signature.name} with {context.arguments}")

    def log_success(result):
        print(f"Success! Result: {result.value}")

    def log_failure(result):
        print(f"Failed! Error: {result.exception}")

    @CallPyBack(
        observers=[on_call(log_call), on_success(log_success), on_failure(log_failure)],
    )
    def divide(a, b):
        """Example function with potential for error."""
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b

    # Test successful execution
    print("=== Successful execution ===")
    result = divide(10, 2)
    print(f"Final result: {result}")

    # Test error handling
    print("\n=== Error handling ===")
    try:
        result = divide(10, 0)
    except ValueError:
        pass  # print(f"Failed! Error: {e}")
    print(f"Final result: {result}")  # Should return None (default_return)


def variable_extraction_example():
    """Example showing variable extraction."""

    def show_variables(local_variables):
        print(f"Captured variables: {local_variables}")

    @CallPyBack(
        observers=[on_success(show_variables)],
        variable_names=["step1", "step2", "final_calculation"],
    )
    def multi_step_calculation(x, y):
        """Function with multiple steps."""
        step1 = x * 2
        step2 = y + 5
        final_calculation = step1 + step2
        return final_calculation

    print("=== Variable extraction ===")
    result = multi_step_calculation(3, 4)
    print(f"Final result: {result}")


def monitoring_example():
    """Example with comprehensive monitoring."""

    # Set up monitoring
    metrics = MetricsObserver()
    logger = LoggingObserver()

    @CallPyBack(observers=[metrics, logger])
    def monitored_function(data):
        """Function with monitoring."""
        processed = data.upper() if isinstance(data, str) else str(data)
        return f"Processed: {processed}"

    print("=== Monitoring example ===")

    # Execute multiple times
    for i in range(3):
        result = monitored_function(f"data_{i}")
        print(f"Result {i}: {result}")

    # Show metrics
    print("\nMetrics:")
    print(metrics.get_metrics())


def error_handling_example():
    """Example showing advanced error handling."""

    call_log = []
    success_log = []
    failure_log = []

    @CallPyBack(
        observers=[
            on_call(lambda context: call_log.append(context.function_signature.name)),
            on_success(lambda result: success_log.append(result.value)),
            on_failure(lambda result: failure_log.append(str(result.exception))),
        ],
        exception_classes=(ValueError, TypeError),
        default_return="handled_error",
    )
    def error_prone_function(operation, value):
        """Function that can fail in different ways."""
        if operation == "divide_by_zero":
            return 10 / 0  # Will raise ZeroDivisionError (not caught)
        elif operation == "invalid_type":
            raise TypeError("Invalid type provided")
        elif operation == "business_error":
            raise ValueError("Business rule violation")
        else:
            return f"Success: {value}"

    print("=== Error handling example ===")

    # Test successful execution
    result1 = error_prone_function("success", "test_value")
    print(f"Success case: {result1}")

    # Test handled error (TypeError)
    result2 = error_prone_function("invalid_type", "test")
    print(f"Handled TypeError: {result2}")

    # Test handled error (ValueError)
    result3 = error_prone_function("business_error", "test")
    print(f"Handled ValueError: {result3}")

    # Test unhandled error (will raise)
    try:
        result4 = error_prone_function("divide_by_zero", "test")
        print(f"This shouldn't print: {result4}")
    except ZeroDivisionError:
        print("ZeroDivisionError not caught (as expected)")

    print(f"\nCall log: {call_log}")
    print(f"Success log: {success_log}")
    print(f"Failure log: {failure_log}")


if __name__ == "__main__":
    basic_example()
    print("\n" + "=" * 50 + "\n")
    variable_extraction_example()
    print("\n" + "=" * 50 + "\n")
    monitoring_example()
    print("\n" + "=" * 50 + "\n")
    error_handling_example()
