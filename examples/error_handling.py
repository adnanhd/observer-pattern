#!/usr/bin/env python3
"""
Error Handling Strategies Example
Demonstrates different error handling patterns and graceful degradation.
"""

from collections import defaultdict

from callpyback import CallPyBack, on_failure

# Global error statistics
error_stats = defaultdict(int)


def track_errors(result):
    """Track different types of errors."""
    error_type = type(result.exception).__name__
    error_stats[error_type] += 1
    print(f"🚨 Tracked {error_type}: {result.exception}")


# Strategy 1: Graceful degradation for external services
@CallPyBack(
    observers=[on_failure(track_errors)],
    exception_classes=(ConnectionError, TimeoutError, ValueError),
    default_return={"status": "degraded", "fallback": True},
)
def external_service_call(service_type, data):
    """Simulate external service calls with potential failures."""
    if service_type == "database":
        if data.get("invalid"):
            raise ValueError("Invalid database query")
        return {"status": "success", "data": f"db_result_{data.get('id', 'unknown')}"}

    elif service_type == "api":
        if data.get("timeout"):
            raise TimeoutError("API call timed out")
        return {
            "status": "success",
            "response": f"api_data_{data.get('endpoint', 'default')}",
        }

    elif service_type == "network":
        if data.get("connection_error"):
            raise ConnectionError("Network service unavailable")
        return {"status": "success", "network_data": "connected"}

    elif service_type == "critical":
        # This will not be caught - critical errors should propagate
        raise RuntimeError("Critical system failure")

    return {"status": "success", "service": service_type}


# Strategy 2: Retry with exponential backoff simulation
retry_attempts = {"count": 0}


def track_retry_failures(result):
    """Track failures for retry logic."""
    retry_attempts["count"] += 1
    error_type = type(result.exception).__name__
    print(f"🔄 Retry attempt {retry_attempts['count']} failed: {error_type}")


@CallPyBack(
    observers=[on_failure(track_retry_failures)],
    exception_classes=(ConnectionError, TimeoutError),
    default_return={"status": "max_retries_exceeded"},
)
def retry_service_call(operation, max_retries=3):
    """Simulate service with retry logic."""
    import random

    # Simulate failure rate that decreases with retries
    failure_rate = max(0.1, 0.8 - (retry_attempts["count"] * 0.2))

    if retry_attempts["count"] < max_retries and random.random() < failure_rate:
        if random.random() < 0.5:
            raise ConnectionError(
                f"Connection failed (attempt {retry_attempts['count'] + 1})"
            )
        else:
            raise TimeoutError(f"Timeout (attempt {retry_attempts['count'] + 1})")

    # Reset retry count on success
    retry_attempts["count"] = 0
    return {
        "status": "success",
        "operation": operation,
        "retries": retry_attempts["count"],
    }


# Strategy 3: Circuit breaker pattern
circuit_state = {"failures": 0, "state": "CLOSED", "last_failure": 0}


def circuit_breaker_check(context):
    """Check circuit breaker state before execution."""
    import time

    if circuit_state["state"] == "OPEN":
        time_since_failure = time.time() - circuit_state["last_failure"]
        if time_since_failure > 5:  # 5 second timeout
            circuit_state["state"] = "HALF_OPEN"
            print("🔄 Circuit breaker: HALF_OPEN")
        else:
            print("🔴 Circuit breaker: OPEN - request blocked")
            return {"status": "circuit_open", "blocked": True}


def track_circuit_failures(result):
    """Track failures for circuit breaker."""
    import time

    circuit_state["failures"] += 1
    circuit_state["last_failure"] = time.time()

    if circuit_state["failures"] >= 3:  # Threshold
        circuit_state["state"] = "OPEN"
        print(f"🔴 Circuit breaker OPENED after {circuit_state['failures']} failures")


def track_circuit_success(result):
    """Reset circuit breaker on success."""
    if circuit_state["state"] == "HALF_OPEN":
        circuit_state["state"] = "CLOSED"
        circuit_state["failures"] = 0
        print("✅ Circuit breaker CLOSED - service recovered")


@CallPyBack(
    observers=[
        on_call(circuit_breaker_check),
        on_success(track_circuit_success),
        on_failure(track_circuit_failures),
    ],
    exception_classes=(ConnectionError, RuntimeError),
    default_return={"status": "service_unavailable"},
)
def protected_service(should_fail=False):
    """Service protected by circuit breaker."""
    if circuit_state["state"] == "OPEN":
        return {"status": "blocked_by_circuit_breaker"}

    if should_fail:
        raise ConnectionError("Service failure")

    return {"status": "success", "protected": True}


if __name__ == "__main__":
    print("=== Error Handling Strategies ===")

    # Test error handling strategies
    print("1. Testing graceful degradation:")
    degradation_tests = [
        ("database", {"id": "123"}),  # Success
        ("database", {"invalid": True}),  # ValueError - handled
        ("api", {"endpoint": "users"}),  # Success
        ("api", {"timeout": True}),  # TimeoutError - handled
        ("network", {}),  # Success
        ("network", {"connection_error": True}),  # ConnectionError - handled
    ]

    for service, data in degradation_tests:
        try:
            result = external_service_call(service, data)
            print(f"  {service}: {result}")
        except Exception as e:
            print(f"  {service}: UNCAUGHT - {e}")

    print(f"\n2. Testing retry logic:")
    # Test retry mechanism multiple times
    for i in range(3):
        retry_attempts["count"] = 0  # Reset for each test
        result = retry_service_call(f"operation_{i+1}")
        print(f"  Operation {i+1}: {result}")

    print(f"\n3. Testing circuit breaker:")
    # Test circuit breaker by causing failures
    for i in range(6):
        result = protected_service(should_fail=(i < 4))  # First 4 will fail
        print(f"  Request {i+1}: {result}")

    # Test critical error (should propagate)
    print(f"\n4. Testing critical error propagation:")
    try:
        external_service_call("critical", {})
    except RuntimeError as e:
        print(f"  Critical error correctly propagated: {e}")

    # Error handling summary
    print(f"\nError Handling Summary:")
    print(f"  Error types encountered: {len(error_stats)}")
    for error_type, count in error_stats.items():
        print(f"    {error_type}: {count} occurrences")

    print(f"  Circuit breaker final state: {circuit_state['state']}")
    print(f"  Circuit breaker failures: {circuit_state['failures']}")
