"""Comprehensive error handling examples."""

import logging
from callpyback import CallPyBack, on_failure
from callpyback.management.error_handling import (
    ErrorHandlerBuilder,
    create_standard_error_chain,
    create_robust_error_chain,
    BusinessLogicErrorHandler,
    SecurityErrorHandler,
    ConditionalErrorHandler,
)

# Set up logging to see error handling in action
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def basic_error_handling_example():
    """Example using the standard error handling chain."""

    failure_log = []

    @CallPyBack(
        observers=[
            on_failure(lambda result: failure_log.append(str(result.exception)))
        ],
        exception_classes=(ValueError, TypeError, TimeoutError, ConnectionError),
        default_return="handled_by_chain",
    )
    def error_demo_function(error_type):
        """Function that can produce different types of errors."""
        if error_type == "timeout":
            raise TimeoutError("Operation timed out")
        elif error_type == "validation":
            raise ValueError("Invalid input provided")
        elif error_type == "network":
            raise ConnectionError("Network connection failed")
        elif error_type == "type":
            raise TypeError("Wrong type provided")
        else:
            return f"Success with {error_type}"

    print("=== Basic Error Handling Example ===")

    test_cases = ["success", "timeout", "validation", "network", "type"]

    for case in test_cases:
        try:
            result = error_demo_function(case)
            print(f"{case}: {result}")
        except Exception as e:
            print(f"{case}: Unhandled exception - {e}")

    print(f"Caught failures: {failure_log}")


def custom_error_chain_example():
    """Example building a custom error handler chain."""

    # Custom business logic error mapping
    business_error_mapping = {
        ValueError: {"status": "error", "code": "INVALID_INPUT"},
        TypeError: {"status": "error", "code": "TYPE_MISMATCH"},
    }

    # Build custom error chain
    custom_chain = (
        ErrorHandlerBuilder()
        .add_timeout_handler("timeout_fallback")
        .add_business_logic_handler(business_error_mapping)
        .add_network_handler(retry_count=1, default_return="network_fallback")
        .add_default_handler("unknown_error")
        .build()
    )

    # Create a decorator with the custom error chain
    custom_decorator = CallPyBack(
        observers=[],
        exception_classes=(Exception,),
        default_return="should_not_reach_here",
    )
    # Replace the error handler
    custom_decorator._error_handler = custom_chain

    @custom_decorator
    def business_function(operation):
        """Function with business logic that can fail."""
        if operation == "invalid_data":
            raise ValueError("Data validation failed")
        elif operation == "wrong_type":
            raise TypeError("Expected string, got integer")
        elif operation == "network_fail":
            raise ConnectionError("Database connection lost")
        elif operation == "timeout":
            raise TimeoutError("Query timed out")
        elif operation == "unknown":
            raise RuntimeError("Unknown system error")
        else:
            return f"Business operation {operation} completed"

    print("\n=== Custom Error Chain Example ===")

    test_cases = [
        "success",
        "invalid_data",
        "wrong_type",
        "network_fail",
        "timeout",
        "unknown",
    ]

    for case in test_cases:
        result = business_function(case)
        print(f"{case}: {result}")


def conditional_error_handling_example():
    """Example using conditional error handlers."""

    def is_critical_error(error, context):
        """Condition: Handle only errors in critical functions."""
        return context.function_signature.name.startswith("critical_")

    def critical_error_handler(error, context):
        """Custom handler for critical errors."""
        return {
            "status": "critical_failure",
            "function": context.function_signature.name,
            "error": str(error),
            "requires_immediate_attention": True,
        }

    def is_user_error(error, context):
        """Condition: Handle user-related errors."""
        user_errors = ["user", "input", "validation"]
        error_msg = str(error).lower()
        return any(keyword in error_msg for keyword in user_errors)

    def user_error_handler(error, context):
        """Custom handler for user errors."""
        return {
            "status": "user_error",
            "message": "Please check your input and try again",
            "details": str(error),
        }

    # Build conditional error chain
    conditional_chain = (
        ErrorHandlerBuilder()
        .add_conditional_handler(is_critical_error, critical_error_handler)
        .add_conditional_handler(is_user_error, user_error_handler)
        .add_default_handler("generic_error")
        .build()
    )

    # Create decorators with custom chain
    critical_decorator = CallPyBack(
        exception_classes=(Exception,), default_return="fallback"
    )
    critical_decorator._error_handler = conditional_chain

    regular_decorator = CallPyBack(
        exception_classes=(Exception,), default_return="fallback"
    )
    regular_decorator._error_handler = conditional_chain

    @critical_decorator
    def critical_system_function(scenario):
        """Critical function that requires special error handling."""
        if scenario == "system_failure":
            raise RuntimeError("Critical system component failed")
        elif scenario == "user_input":
            raise ValueError("User provided invalid input")
        elif scenario == "normal_error":
            raise OSError("Regular system error")
        else:
            return "Critical operation successful"

    @regular_decorator
    def regular_function(scenario):
        """Regular function for comparison."""
        if scenario == "system_failure":
            raise RuntimeError("System component failed")
        elif scenario == "user_input":
            raise ValueError("User provided invalid input")
        else:
            return "Regular operation successful"

    print("\n=== Conditional Error Handling Example ===")

    test_scenarios = ["success", "system_failure", "user_input", "normal_error"]

    print("Critical function results:")
    for scenario in test_scenarios:
        result = critical_system_function(scenario)
        print(f"  {scenario}: {result}")

    print("\nRegular function results:")
    for scenario in test_scenarios[:3]:  # Skip normal_error for regular function
        result = regular_function(scenario)
        print(f"  {scenario}: {result}")


def security_error_handling_example():
    """Example with security-focused error handling."""

    # Set up security audit logger
    security_logger = logging.getLogger("security_audit")
    security_handler = logging.StreamHandler()
    security_handler.setFormatter(
        logging.Formatter("🔒 SECURITY: %(asctime)s - %(message)s")
    )
    security_logger.addHandler(security_handler)
    security_logger.setLevel(logging.CRITICAL)

    # Build security-focused error chain
    security_chain = (
        ErrorHandlerBuilder()
        .add_security_handler(security_logger)
        .add_default_handler("access_denied")
        .build()
    )

    # Create decorator with security chain
    security_decorator = CallPyBack(
        exception_classes=(Exception,), default_return="fallback"
    )
    security_decorator._error_handler = security_chain

    @security_decorator
    def secure_function(action):
        """Function that handles sensitive operations."""
        if action == "unauthorized_access":
            raise PermissionError("Unauthorized access attempt")
        elif action == "auth_failure":
            raise ValueError("Authentication failed - invalid credentials")
        elif action == "access_violation":
            raise RuntimeError("Security policy violation detected")
        elif action == "normal_error":
            raise ValueError("Regular validation error")
        else:
            return f"Secure operation {action} completed"

    print("\n=== Security Error Handling Example ===")

    security_scenarios = [
        "success",
        "unauthorized_access",
        "auth_failure",
        "access_violation",
        "normal_error",
    ]

    for scenario in security_scenarios:
        result = secure_function(scenario)
        print(f"{scenario}: {result}")


def production_error_handling_example():
    """Example showing production-ready error handling."""

    # Create a simple production decorator that doesn't re-raise validation errors
    production_decorator = CallPyBack(
        observers=[],
        exception_classes=(Exception,),
        default_return={"status": "error", "code": "UNKNOWN_ERROR"},
    )

    @production_decorator
    def production_service(operation, data):
        """Production service function."""
        if operation == "validate":
            if not isinstance(data, str):
                raise TypeError(f"Expected string, got {type(data)}")
            if len(data) < 3:
                raise ValueError("Data too short")
        elif operation == "network":
            raise ConnectionError("Service temporarily unavailable")
        elif operation == "timeout":
            raise TimeoutError("Request timed out")
        elif operation == "unknown":
            raise RuntimeError("Unexpected system error")

        return {"status": "success", "data": f"Processed {data}"}

    print("\n=== Production Error Handling Example ===")

    test_cases = [
        ("validate", "hello"),  # Success
        ("validate", 123),  # Type error
        ("validate", "hi"),  # Validation error
        ("network", "data"),  # Network error
        ("timeout", "data"),  # Timeout error
        ("unknown", "data"),  # Unknown error
    ]

    for operation, data in test_cases:
        result = production_service(operation, data)
        print(f"{operation} with {data}: {result}")


if __name__ == "__main__":
    basic_error_handling_example()
    custom_error_chain_example()
    conditional_error_handling_example()
    security_error_handling_example()
    production_error_handling_example()
