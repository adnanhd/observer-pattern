#!/usr/bin/env python3
"""
Basic CallPyBack Usage - Core Callback Patterns
Demonstrates fundamental callback usage with state tracking.
"""

from callpyback import CallPyBack, on_call, on_failure, on_success

# Global execution tracking
execution_log = []


def track_call(context):
    execution_log.append(f"CALL: {context.function_signature.name}")
    print(f"📞 Calling: {context.function_signature.name}")


def track_success(result):
    execution_log.append(f"SUCCESS: {result.value}")
    print(f"✅ Success: {result.value}")


def track_failure(result):
    execution_log.append(f"FAILURE: {result.exception}")
    print(f"❌ Failed: {result.exception}")


@CallPyBack(
    observers=[
        on_call(track_call),
        on_success(track_success),
        on_failure(track_failure),
    ],
    exception_classes=(ValueError, TypeError),
    default_return="handled_gracefully",
)
def demo_function(operation, value):
    """Function that demonstrates different execution paths."""
    if operation == "success":
        return f"Processed: {value}"
    elif operation == "error":
        raise ValueError(f"Invalid operation: {value}")
    elif operation == "type_error":
        raise TypeError(f"Wrong type for: {value}")
    elif operation == "unhandled":
        raise RuntimeError("This won't be caught")
    return f"Unknown operation: {operation}"


if __name__ == "__main__":
    test_cases = [
        ("success", "test_data"),
        ("error", "bad_data"),
        ("type_error", "wrong_type"),
        ("success", "more_data"),
        ("unhandled", "test"),
    ]

    print("Testing callback patterns:")
    for operation, value in test_cases:
        try:
            result = demo_function(operation, value)
            print(f"  Result: {result}")
        except Exception as e:
            # Test unhandled exception (should propagate)
            print(f"  Correctly propagated: {e}")
        print()

    print(f"\nExecution log ({len(execution_log)} events):")
    for event in execution_log:
        print(f"  {event}")
