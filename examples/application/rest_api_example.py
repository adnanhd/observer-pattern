#!/usr/bin/env python3
"""
REST API Monitoring Example
Demonstrates monitoring REST API endpoints with CallPyBack for:
- Request/response logging
- Performance tracking
- Error rate monitoring
- Rate limiting detection
"""

import json
import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Dict, Optional

from callpyback import (
    CallPyBack,
    DefaultErrorHandler,
    ExecutionContext,
    ExecutionState,
    on_call,
    on_completion,
    on_failure,
    on_success,
)
from callpyback.observers.base import BaseObserver


@dataclass
class APIRequest:
    method: str
    endpoint: str
    headers: Dict[str, str]
    body: Optional[str] = None
    user_id: Optional[str] = None


class APIMonitoringObserver(BaseObserver):
    """Comprehensive API monitoring observer"""

    def __init__(self):
        super().__init__(priority=90, name="APIMonitoring")
        self.request_stats = defaultdict(
            lambda: {
                "count": 0,
                "total_time": 0,
                "errors": 0,
                "status_codes": defaultdict(int),
            }
        )
        self.recent_requests = deque(maxlen=100)  # Keep last 100 requests
        self.error_patterns = defaultdict(int)

    def update(self, context: ExecutionContext) -> None:
        if context.state != ExecutionState.COMPLETED:
            return

        # Extract API details
        request = context.arguments.get("request")
        if not request:
            return

        endpoint = request.endpoint
        method = request.method
        key = f"{method} {endpoint}"

        # Update stats
        stats = self.request_stats[key]
        stats["count"] += 1

        if context.result:
            execution_time = getattr(context.result, "execution_time", 0)
            stats["total_time"] += execution_time

            # Track status codes and errors
            response = getattr(context.result, "value", {})
            if isinstance(response, dict):
                status_code = response.get("status_code", 200)
                stats["status_codes"][status_code] += 1

                if status_code >= 400:
                    stats["errors"] += 1
                    error_type = response.get("error_type", "unknown")
                    self.error_patterns[f"{endpoint}:{error_type}"] += 1

        # Track recent requests for analysis
        self.recent_requests.append(
            {
                "timestamp": context.timestamp,
                "endpoint": endpoint,
                "method": method,
                "user_id": request.user_id,
                "execution_time": getattr(context.result, "execution_time", 0),
                "success": context.is_successful,
            }
        )

    def get_endpoint_report(self):
        """Generate endpoint performance report"""
        report = {}
        for endpoint, stats in self.request_stats.items():
            avg_time = stats["total_time"] / stats["count"] if stats["count"] > 0 else 0
            error_rate = (
                (stats["errors"] / stats["count"]) * 100 if stats["count"] > 0 else 0
            )

            report[endpoint] = {
                "requests": stats["count"],
                "avg_response_time": f"{avg_time:.3f}s",
                "error_rate": f"{error_rate:.1f}%",
                "status_codes": dict(stats["status_codes"]),
            }
        return report

    def get_error_analysis(self):
        """Analyze error patterns"""
        return dict(self.error_patterns)


class RateLimitingObserver(BaseObserver):
    """Monitor for rate limiting and unusual patterns"""

    def __init__(self, window_size=60):
        super().__init__(priority=80, name="RateLimiting")
        self.window_size = window_size
        self.user_requests = defaultdict(lambda: deque())
        self.alerts = []

    def update(self, context: ExecutionContext) -> None:
        if context.state != ExecutionState.COMPLETED:
            return

        request = context.arguments.get("request")
        if not request or not request.user_id:
            return

        current_time = time.time()
        user_id = request.user_id

        # Add current request
        self.user_requests[user_id].append(current_time)

        # Remove old requests outside window
        cutoff_time = current_time - self.window_size
        while (
            self.user_requests[user_id] and self.user_requests[user_id][0] < cutoff_time
        ):
            self.user_requests[user_id].popleft()

        # Check for rate limiting
        request_count = len(self.user_requests[user_id])
        if request_count > 100:  # More than 100 requests per minute
            alert = {
                "timestamp": current_time,
                "user_id": user_id,
                "request_count": request_count,
                "endpoint": request.endpoint,
                "alert_type": "rate_limit_exceeded",
            }
            self.alerts.append(alert)
            print(
                f"🚨 Rate limit alert: User {user_id} made {request_count} requests in {self.window_size}s"
            )

    def get_active_users(self):
        """Get currently active users"""
        current_time = time.time()
        cutoff_time = current_time - 300  # 5 minutes

        active_users = {}
        for user_id, requests in self.user_requests.items():
            recent_requests = [r for r in requests if r > cutoff_time]
            if recent_requests:
                active_users[user_id] = len(recent_requests)

        return active_users


# Set up monitoring
api_monitor = APIMonitoringObserver()
rate_limiter = RateLimitingObserver()

# Error handler for API failures
api_error_handler = DefaultErrorHandler(
    default_return={
        "status_code": 500,
        "error": "Internal server error",
        "error_type": "server_error",
    }
)


@CallPyBack(
    observers=[
        api_monitor,
        rate_limiter,
        on_call(
            lambda context: print(
                f"📡 API Call: {context.arguments['request'].method} {context.arguments['request'].endpoint}"
            )
        ),
        on_failure(lambda result: print(f"❌ API Error: {result.exception}")),
    ],
    error_handler=api_error_handler,
    exception_classes=(ConnectionError, TimeoutError, ValueError),
)
def handle_api_request(request: APIRequest) -> Dict[str, Any]:
    """Simulate handling an API request"""

    # Simulate processing time
    processing_time = random.uniform(0.01, 0.5)
    time.sleep(processing_time)

    # Simulate various response scenarios

    # GET endpoints
    if request.method == "GET":
        if request.endpoint == "/api/users":
            return {
                "status_code": 200,
                "data": [{"id": i, "name": f"User {i}"} for i in range(1, 6)],
                "count": 5,
            }
        elif request.endpoint.startswith("/api/users/"):
            user_id = request.endpoint.split("/")[-1]
            if user_id == "999":  # Simulate not found
                return {
                    "status_code": 404,
                    "error": "User not found",
                    "error_type": "not_found",
                }
            return {
                "status_code": 200,
                "data": {"id": user_id, "name": f"User {user_id}"},
            }
        elif request.endpoint == "/api/products":
            # Simulate occasional database timeout
            if random.random() < 0.1:
                raise ConnectionError("Database connection timeout")
            return {
                "status_code": 200,
                "data": [{"id": i, "name": f"Product {i}"} for i in range(1, 11)],
            }

    # POST endpoints
    elif request.method == "POST":
        if request.endpoint == "/api/users":
            # Simulate validation error
            if request.body and '"email"' not in request.body:
                return {
                    "status_code": 400,
                    "error": "Email is required",
                    "error_type": "validation_error",
                }
            return {
                "status_code": 201,
                "data": {"id": random.randint(100, 999), "message": "User created"},
            }
        elif request.endpoint == "/api/orders":
            # Simulate payment processing error
            if random.random() < 0.15:
                return {
                    "status_code": 402,
                    "error": "Payment processing failed",
                    "error_type": "payment_error",
                }
            return {
                "status_code": 201,
                "data": {"order_id": f"ORD-{random.randint(1000, 9999)}"},
            }

    # PUT/PATCH endpoints
    elif request.method in ["PUT", "PATCH"]:
        if request.endpoint.startswith("/api/users/"):
            # Simulate authorization error
            if not request.headers.get("Authorization"):
                return {
                    "status_code": 401,
                    "error": "Authorization required",
                    "error_type": "auth_error",
                }
            return {"status_code": 200, "data": {"message": "User updated"}}

    # DELETE endpoints
    elif request.method == "DELETE":
        if request.endpoint.startswith("/api/users/"):
            # Simulate forbidden error
            if random.random() < 0.2:
                return {
                    "status_code": 403,
                    "error": "Insufficient permissions",
                    "error_type": "permission_error",
                }
            return {"status_code": 204, "message": "User deleted"}

    # Default response
    return {"status_code": 200, "data": {"message": "Request processed successfully"}}


def simulate_api_traffic():
    """Simulate realistic API traffic patterns"""

    # Define realistic endpoint patterns
    endpoints = [
        ("GET", "/api/users", 0.3),
        ("GET", "/api/users/123", 0.2),
        ("GET", "/api/products", 0.15),
        ("POST", "/api/users", 0.1),
        ("POST", "/api/orders", 0.1),
        ("PUT", "/api/users/123", 0.08),
        ("DELETE", "/api/users/456", 0.05),
        ("GET", "/api/users/999", 0.02),  # Not found scenario
    ]

    users = [f"user_{i}" for i in range(1, 21)]

    print("🚀 Starting API traffic simulation...")
    print("=" * 50)

    # Simulate 50 API calls
    for i in range(50):
        # Select endpoint based on probability
        rand = random.random()
        cumulative = 0
        for method, endpoint, probability in endpoints:
            cumulative += probability
            if rand <= cumulative:
                break

        # Create request
        user_id = random.choice(users)
        headers = {"User-Agent": "TestClient/1.0"}

        # Add auth header for some requests
        if random.random() < 0.8:
            headers["Authorization"] = f"Bearer token_{user_id}"

        body = None
        if method == "POST" and endpoint == "/api/users":
            body = json.dumps(
                {"name": f"New User {i}", "email": f"user{i}@example.com"}
            )
        elif method == "POST" and endpoint == "/api/orders":
            body = json.dumps(
                {"product_id": random.randint(1, 10), "quantity": random.randint(1, 5)}
            )

        request = APIRequest(
            method=method,
            endpoint=endpoint,
            headers=headers,
            body=body,
            user_id=user_id,
        )

        try:
            response = handle_api_request(request)
            status = response.get("status_code", 200)
            print(f"  {method} {endpoint} -> {status}")
        except Exception as e:
            print(f"  {method} {endpoint} -> ERROR: {e}")

        # Random delay between requests
        time.sleep(random.uniform(0.01, 0.1))

    print("\n" + "=" * 50)
    print("📊 API TRAFFIC ANALYSIS")
    print("=" * 50)

    # Endpoint performance report
    endpoint_report = api_monitor.get_endpoint_report()
    print("\n🎯 Endpoint Performance:")
    for endpoint, stats in endpoint_report.items():
        print(f"  {endpoint}:")
        print(f"    Requests: {stats['requests']}")
        print(f"    Avg Response Time: {stats['avg_response_time']}")
        print(f"    Error Rate: {stats['error_rate']}")
        print(f"    Status Codes: {stats['status_codes']}")

    # Error analysis
    error_analysis = api_monitor.get_error_analysis()
    if error_analysis:
        print(f"\n🔥 Error Patterns:")
        for pattern, count in error_analysis.items():
            print(f"  {pattern}: {count} occurrences")

    # Active users
    active_users = rate_limiter.get_active_users()
    print(f"\n👥 Active Users (last 5 min): {len(active_users)}")
    for user_id, request_count in sorted(
        active_users.items(), key=lambda x: x[1], reverse=True
    )[:10]:
        print(f"  {user_id}: {request_count} requests")

    # Rate limiting alerts
    if rate_limiter.alerts:
        print(f"\n🚨 Rate Limiting Alerts: {len(rate_limiter.alerts)}")
        for alert in rate_limiter.alerts[-5:]:  # Show last 5 alerts
            print(
                f"  {alert['user_id']} exceeded limit with {alert['request_count']} requests"
            )


if __name__ == "__main__":
    simulate_api_traffic()
