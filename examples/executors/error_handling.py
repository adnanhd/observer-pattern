#!/usr/bin/env python3
"""
Error Handling Examples

This example demonstrates error handling patterns when using CallPyBack
executors, including exception handling, timeouts, and graceful degradation.
"""

import random
import time

from callpyback import ExecutionMode, Executor, TaskResult, TaskStatus

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

    with Executor(mode=ExecutionMode.THREAD, max_workers=2) as executor:
        # Submit tasks that may fail
        tasks = [
            ("valid", executor.submit(division, 10, 2)),
            ("division_by_zero", executor.submit(division, 10, 0)),
            ("valid_2", executor.submit(division, 20, 4)),
        ]

        for name, task_id in tasks:
            result = executor.result(task_id, timeout=5.0)

            if result.is_success:
                print(f"  {name}: SUCCESS - {result.value}")
            else:
                print(f"  {name}: FAILED - {result.error_type}: {result.error}")


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

    with Executor(mode=ExecutionMode.THREAD, max_workers=2) as executor:
        task_ids = [executor.submit(validate_and_process, data) for data in test_cases]

        for i, task_id in enumerate(task_ids):
            result = executor.result(task_id, timeout=5.0)

            if result.is_success:
                print(f"  Case {i + 1}: SUCCESS - {result.value}")
            else:
                print(f"  Case {i + 1}: {result.error_type} - {result.error}")


# ============================================================================
# Example 3: Retry Pattern (Manual)
# ============================================================================


def retry_pattern():
    """Demonstrate manual retry pattern for flaky operations."""
    print("\n" + "=" * 60)
    print("Example 3: Manual Retry Pattern")
    print("=" * 60)

    def execute_with_retry(executor, func, *args, max_retries=3, **kwargs):
        """Execute a function with retries."""
        last_error = None
        for attempt in range(1, max_retries + 1):
            task_id = executor.submit(func, *args, **kwargs)
            result = executor.result(task_id, timeout=5.0)

            if result.is_success:
                return result.value, attempt

            last_error = result.error
            print(f"    Attempt {attempt} failed: {last_error}")

        raise Exception(f"All {max_retries} attempts failed. Last error: {last_error}")

    with Executor(mode=ExecutionMode.THREAD, max_workers=1) as executor:
        # Try a flaky operation with retries
        try:
            result, attempts = execute_with_retry(
                executor,
                flaky_operation,
                0.4,  # 40% success rate
                max_retries=5,
            )
            print(f"  Result: {result} (succeeded on attempt {attempts})")
        except Exception as e:
            print(f"  Failed: {e}")


# ============================================================================
# Example 4: Timeout Handling
# ============================================================================


def timeout_handling():
    """Demonstrate timeout handling."""
    print("\n" + "=" * 60)
    print("Example 4: Timeout Handling")
    print("=" * 60)

    with Executor(mode=ExecutionMode.THREAD, max_workers=2) as executor:
        # Fast task
        fast_task = executor.submit(slow_operation, 0.1)

        # Slow task
        slow_task = executor.submit(slow_operation, 10.0)

        # Get fast task result
        fast_result = executor.result(fast_task, timeout=5.0)
        print(f"  Fast task: {fast_result.value}")

        # Try to get slow task result with short timeout
        try:
            slow_result = executor.result(slow_task, timeout=0.5)
            print(f"  Slow task: {slow_result.value}")
        except TimeoutError:
            print("  Slow task: TIMEOUT - Task is still running")
            print("  (Task will complete in background when executor closes)")


# ============================================================================
# Example 5: Graceful Degradation
# ============================================================================


def graceful_degradation():
    """Demonstrate graceful degradation pattern."""
    print("\n" + "=" * 60)
    print("Example 5: Graceful Degradation")
    print("=" * 60)

    def fetch_data(url: str) -> str:
        """Fetch data, may fail for primary sources."""
        time.sleep(0.05)  # Simulate network
        if "primary" in url:
            raise ConnectionError("Primary source unavailable")
        return f"Data from {url}"

    def get_data_with_fallback(executor, url: str, default: str) -> str:
        """Get data with graceful fallback."""
        task_id = executor.submit(fetch_data, url)
        result = executor.result(task_id, timeout=5.0)

        if result.is_success:
            return result.value
        else:
            print(f"    Warning: {url} failed, using fallback")
            return default

    with Executor(mode=ExecutionMode.THREAD, max_workers=2) as executor:
        # Try primary sources with fallbacks
        sources = [
            ("primary-api.example.com", "cached_data_1"),
            ("secondary-api.example.com", "cached_data_2"),
            ("primary-backup.example.com", "cached_data_3"),
        ]

        for url, fallback in sources:
            data = get_data_with_fallback(executor, url, fallback)
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
        if result.status == TaskStatus.COMPLETED:
            return f"SUCCESS: {result.value}"
        elif result.status == TaskStatus.FAILED:
            return f"FAILED: {result.error_type} - {result.error}"
        elif result.status == TaskStatus.CANCELLED:
            return "CANCELLED: Operation was cancelled"
        elif result.status == TaskStatus.RUNNING:
            return "RUNNING: Still in progress"
        elif result.status == TaskStatus.PENDING:
            return "PENDING: Not yet started"
        else:
            return f"UNKNOWN: {result.status}"

    with Executor(mode=ExecutionMode.THREAD, max_workers=2) as executor:
        # Various outcomes
        success_task = executor.submit(lambda: 42)
        failure_task = executor.submit(lambda: 1 / 0)

        for name, task_id in [("Success", success_task), ("Failure", failure_task)]:
            result = executor.result(task_id, timeout=5.0)
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

    with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
        task_ids = [executor.submit(maybe_fail, i) for i in range(8)]

        successes = []
        failures = []

        for i, task_id in enumerate(task_ids):
            result = executor.result(task_id, timeout=5.0)

            if result.is_success:
                successes.append((i, result.value))
            else:
                failures.append((i, result.error))

        print(f"  Successes: {len(successes)}")
        for idx, value in successes:
            print(f"    Task {idx}: {value}")

        print(f"  Failures: {len(failures)}")
        for idx, error in failures:
            print(f"    Task {idx}: {error}")

        # Summary statistics
        total = len(successes) + len(failures)
        success_rate = len(successes) / total if total > 0 else 0
        print(f"\n  Success rate: {success_rate:.0%}")


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
