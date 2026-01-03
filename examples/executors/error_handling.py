#!/usr/bin/env python3
"""
Error Handling Examples

This example demonstrates error handling patterns when using CallPyBack
executors, including exception handling, retries, timeouts, and
graceful degradation.
"""

import random
import time
from typing import Optional

from callpyback import (
    ProcessExecutor,
    TaskResult,
    TaskStatus,
    ThreadExecutor,
)

# ============================================================================
# Helper Functions
# ============================================================================


def flaky_operation(success_rate: float = 0.5) -> str:
    """Operation that randomly fails."""
    if random.random() > success_rate:
        raise ConnectionError("Random failure occurred")
    return "Operation succeeded"


def slow_operation(duration: float) -> str:
    """Operation that takes a specified time."""
    time.sleep(duration)
    return f"Completed after {duration}s"


def division(a: int, b: int) -> float:
    """Division that may raise ZeroDivisionError."""
    return a / b


def validate_and_process(data: dict) -> dict:
    """Validate and process data, may raise various errors."""
    if not isinstance(data, dict):
        raise TypeError("Data must be a dictionary")
    if "value" not in data:
        raise KeyError("Missing required key: 'value'")
    if data["value"] < 0:
        raise ValueError("Value must be non-negative")
    return {"result": data["value"] * 2, "processed": True}


# ============================================================================
# Example 1: Basic Exception Handling
# ============================================================================


def basic_exception_handling():
    """Demonstrate basic exception handling."""
    print("\n" + "=" * 60)
    print("Example 1: Basic Exception Handling")
    print("=" * 60)

    with ThreadExecutor(max_workers=2) as executor:
        # Submit tasks that may fail
        tasks = [
            ("valid", executor.submit(division, 10, 2)),
            ("division_by_zero", executor.submit(division, 10, 0)),
            ("valid_2", executor.submit(division, 20, 4)),
        ]

        for name, task_id in tasks:
            result = executor.get_result(task_id, timeout=5.0)

            if result.is_success:
                print(f"  {name}: SUCCESS - {result.value}")
            else:
                print(f"  {name}: FAILED - {type(result.exception).__name__}")


# ============================================================================
# Example 2: Handling Different Exception Types
# ============================================================================


def exception_type_handling():
    """Demonstrate handling different exception types."""
    print("\n" + "=" * 60)
    print("Example 2: Handling Different Exception Types")
    print("=" * 60)

    test_cases = [
        {"value": 10},  # Valid
        {"value": -5},  # ValueError
        {"wrong_key": 10},  # KeyError
        "not a dict",  # TypeError
    ]

    with ThreadExecutor(max_workers=2) as executor:
        task_ids = [executor.submit(validate_and_process, data) for data in test_cases]

        for i, task_id in enumerate(task_ids):
            result = executor.get_result(task_id, timeout=5.0)

            if result.is_success:
                print(f"  Case {i + 1}: SUCCESS - {result.value}")
            else:
                exc = result.exception
                exc_type = type(exc).__name__
                print(f"  Case {i + 1}: {exc_type} - {exc}")


# ============================================================================
# Example 3: Retry Pattern
# ============================================================================


def retry_pattern():
    """Demonstrate retry pattern for flaky operations."""
    print("\n" + "=" * 60)
    print("Example 3: Retry Pattern")
    print("=" * 60)

    def flaky_with_tracking():
        """Flaky operation with attempt tracking."""
        flaky_with_tracking.attempts = getattr(flaky_with_tracking, "attempts", 0) + 1
        if flaky_with_tracking.attempts < 3:
            raise ConnectionError(f"Attempt {flaky_with_tracking.attempts} failed")
        return f"Succeeded on attempt {flaky_with_tracking.attempts}"

    # Reset counter
    flaky_with_tracking.attempts = 0

    with ThreadExecutor(max_workers=1) as executor:
        # Submit with retries
        task_id = executor.submit(flaky_with_tracking, max_retries=5)
        result = executor.get_result(task_id, timeout=10.0)

        if result.is_success:
            print(f"  Result: {result.value}")
        else:
            print(f"  Failed after retries: {result.exception}")


# ============================================================================
# Example 4: Timeout Handling
# ============================================================================


def timeout_handling():
    """Demonstrate timeout handling."""
    print("\n" + "=" * 60)
    print("Example 4: Timeout Handling")
    print("=" * 60)

    with ThreadExecutor(max_workers=2) as executor:
        # Fast task
        fast_task = executor.submit(slow_operation, 0.1)

        # Slow task
        slow_task = executor.submit(slow_operation, 10.0)

        # Get fast task result
        fast_result = executor.get_result(fast_task, timeout=5.0)
        print(f"  Fast task: {fast_result.value}")

        # Try to get slow task result with timeout
        try:
            slow_result = executor.get_result(slow_task, timeout=0.5)
            print(f"  Slow task: {slow_result.value}")
        except TimeoutError:
            print("  Slow task: TIMEOUT - Task is still running")

            # Cancel the slow task
            cancelled = executor.cancel(slow_task)
            print(f"  Cancelled: {cancelled}")


# ============================================================================
# Example 5: Graceful Degradation
# ============================================================================


def graceful_degradation():
    """Demonstrate graceful degradation pattern."""
    print("\n" + "=" * 60)
    print("Example 5: Graceful Degradation")
    print("=" * 60)

    def fetch_with_fallback(primary_url: str, fallback_value: str) -> str:
        """Fetch with fallback on failure."""
        # Simulate primary source failure
        if "primary" in primary_url:
            raise ConnectionError("Primary source unavailable")
        return f"Data from {primary_url}"

    def get_data_with_fallback(executor, url: str, default: str) -> str:
        """Get data with graceful fallback."""
        task_id = executor.submit(fetch_with_fallback, url, default)
        result = executor.get_result(task_id, timeout=5.0)

        if result.is_success:
            return result.value
        else:
            print(f"    Warning: {url} failed, using fallback")
            return default

    with ThreadExecutor(max_workers=2) as executor:
        # Try primary sources with fallbacks
        sources = [
            ("primary-api.example.com", "cached_data_1"),
            ("secondary-api.example.com", "cached_data_2"),
            ("primary-backup.example.com", "cached_data_3"),
        ]

        results = []
        for url, fallback in sources:
            data = get_data_with_fallback(executor, url, fallback)
            results.append(data)
            print(f"  {url}: {data}")


# ============================================================================
# Example 6: Comprehensive Status Handling
# ============================================================================


def comprehensive_status_handling():
    """Demonstrate handling all task statuses."""
    print("\n" + "=" * 60)
    print("Example 6: Comprehensive Status Handling")
    print("=" * 60)

    def handle_result(result: TaskResult) -> str:
        """Handle task result based on status."""
        match result.status:
            case TaskStatus.COMPLETED:
                return f"SUCCESS: {result.value}"
            case TaskStatus.FAILED:
                return f"FAILED: {type(result.exception).__name__}"
            case TaskStatus.TIMEOUT:
                return "TIMEOUT: Operation took too long"
            case TaskStatus.CANCELLED:
                return "CANCELLED: Operation was cancelled"
            case _:
                return f"UNKNOWN: {result.status}"

    with ThreadExecutor(max_workers=2) as executor:
        # Various outcomes
        success_task = executor.submit(lambda: 42)
        failure_task = executor.submit(lambda: 1 / 0)

        for name, task_id in [("Success", success_task), ("Failure", failure_task)]:
            result = executor.get_result(task_id, timeout=5.0)
            outcome = handle_result(result)
            print(f"  {name}: {outcome}")


# ============================================================================
# Example 7: Error Aggregation
# ============================================================================


def error_aggregation():
    """Demonstrate aggregating errors from multiple tasks."""
    print("\n" + "=" * 60)
    print("Example 7: Error Aggregation")
    print("=" * 60)

    def maybe_fail(index: int) -> str:
        """Task that fails for odd indices."""
        if index % 2 == 1:
            raise ValueError(f"Task {index} failed")
        return f"Task {index} succeeded"

    with ThreadExecutor(max_workers=4) as executor:
        task_ids = [executor.submit(maybe_fail, i) for i in range(8)]

        successes = []
        failures = []

        for i, task_id in enumerate(task_ids):
            result = executor.get_result(task_id, timeout=5.0)

            if result.is_success:
                successes.append((i, result.value))
            else:
                failures.append((i, str(result.exception)))

        print(f"  Successes: {len(successes)}")
        for idx, value in successes:
            print(f"    Task {idx}: {value}")

        print(f"  Failures: {len(failures)}")
        for idx, error in failures:
            print(f"    Task {idx}: {error}")

        # Summary statistics
        stats = executor.get_stats()
        print(f"\n  Success rate: {stats.success_rate:.0%}")


# ============================================================================
# Main
# ============================================================================


def main():
    print("=" * 60)
    print("CallPyBack Error Handling Examples")
    print("=" * 60)

    basic_exception_handling()
    exception_type_handling()
    retry_pattern()
    timeout_handling()
    graceful_degradation()
    comprehensive_status_handling()
    error_aggregation()

    print("\n" + "=" * 60)
    print("All examples completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
