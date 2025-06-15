#!/usr/bin/env python3
"""
Uses existing CallPyBack plugins: EventBus, ThreadExecutor
"""

import json
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from callpyback import CallPyBack, on_call, on_failure, on_success
from callpyback.observers.base import BaseObserver
from callpyback.plugins.core.message_queue import EventBus
from callpyback.plugins.executors.thread_executor import ThreadExecutor


class HTTPMethod(Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


@dataclass
class APIRequest:
    method: HTTPMethod
    endpoint: str
    headers: Dict[str, str]
    body: Optional[str] = None
    query_params: Optional[Dict[str, str]] = None
    user_id: Optional[str] = None


@dataclass
class APIResponse:
    status_code: int
    data: Any = None
    headers: Dict[str, str] = None
    error: Optional[str] = None


class APIMetricsObserver(BaseObserver):
    """API metrics and monitoring"""

    def __init__(self):
        super().__init__(priority=90, name="APIMetrics")
        self.endpoint_stats = {}
        self.status_codes = {200: 0, 400: 0, 404: 0, 500: 0}
        self.total_requests = 0
        self.total_response_time = 0.0
        self.errors = 0

    def update(self, context):
        if context.state.name == "COMPLETED":
            self.total_requests += 1

            if context.result and context.result.value:
                result = context.result.value
                endpoint = result.get("endpoint", "unknown")
                response_time = result.get("response_time", 0)
                status_code = result.get("status_code", 500)

                # Track endpoint stats
                if endpoint not in self.endpoint_stats:
                    self.endpoint_stats[endpoint] = {
                        "requests": 0,
                        "total_time": 0.0,
                        "errors": 0,
                    }

                self.endpoint_stats[endpoint]["requests"] += 1
                self.endpoint_stats[endpoint]["total_time"] += response_time

                # Track status codes
                if status_code in self.status_codes:
                    self.status_codes[status_code] += 1

                # Track errors
                if status_code >= 400:
                    self.endpoint_stats[endpoint]["errors"] += 1
                    self.errors += 1

                self.total_response_time += response_time

        elif context.state.name == "FAILED":
            self.errors += 1


# Global instances
api_observer = APIMetricsObserver()
event_bus = EventBus()
thread_executor = ThreadExecutor(max_workers=6)


# Mock API handlers
class MockAPIHandlers:
    """Mock REST API endpoint handlers"""

    @staticmethod
    def handle_users(request: APIRequest) -> APIResponse:
        """Handle /api/users endpoints"""

        if request.method == HTTPMethod.GET:
            if request.endpoint == "/api/users":
                # List users
                users = [
                    {"id": i, "name": f"User {i}", "email": f"user{i}@example.com"}
                    for i in range(1, 6)
                ]
                return APIResponse(200, {"users": users, "total": len(users)})

            elif "/api/users/" in request.endpoint:
                # Get specific user
                user_id = request.endpoint.split("/")[-1]
                if user_id == "999":  # Simulate not found
                    return APIResponse(404, error="User not found")

                return APIResponse(
                    200,
                    {
                        "id": user_id,
                        "name": f"User {user_id}",
                        "email": f"user{user_id}@example.com",
                        "created_at": time.time(),
                    },
                )

        elif request.method == HTTPMethod.POST:
            # Create user
            if not request.body:
                return APIResponse(400, error="Request body required")

            try:
                data = json.loads(request.body)
                if "email" not in data:
                    return APIResponse(400, error="Email is required")

                return APIResponse(
                    201,
                    {
                        "id": random.randint(100, 999),
                        "message": "User created successfully",
                        "email": data["email"],
                    },
                )
            except json.JSONDecodeError:
                return APIResponse(400, error="Invalid JSON")

        elif request.method == HTTPMethod.PUT and "/api/users/" in request.endpoint:
            # Update user
            user_id = request.endpoint.split("/")[-1]
            return APIResponse(
                200,
                {
                    "id": user_id,
                    "message": "User updated successfully",
                    "updated_at": time.time(),
                },
            )

        elif request.method == HTTPMethod.DELETE and "/api/users/" in request.endpoint:
            # Delete user
            user_id = request.endpoint.split("/")[-1]
            return APIResponse(200, {"message": f"User {user_id} deleted successfully"})

        return APIResponse(405, error="Method not allowed")

    @staticmethod
    def handle_products(request: APIRequest) -> APIResponse:
        """Handle /api/products endpoints"""

        # Simulate occasional database timeout
        if random.random() < 0.1:
            return APIResponse(500, error="Database connection timeout")

        if request.method == HTTPMethod.GET:
            products = [
                {"id": i, "name": f"Product {i}", "price": random.uniform(10, 100)}
                for i in range(1, 11)
            ]
            return APIResponse(200, {"products": products, "total": len(products)})

        elif request.method == HTTPMethod.POST:
            return APIResponse(
                201,
                {
                    "id": random.randint(100, 999),
                    "message": "Product created successfully",
                },
            )

        return APIResponse(405, error="Method not allowed")

    @staticmethod
    def handle_orders(request: APIRequest) -> APIResponse:
        """Handle /api/orders endpoints"""

        if request.method == HTTPMethod.POST:
            # Simulate payment processing error
            if random.random() < 0.15:
                return APIResponse(402, error="Payment processing failed")

            return APIResponse(
                201,
                {
                    "order_id": f"ORD-{random.randint(1000, 9999)}",
                    "status": "created",
                    "total": random.uniform(50, 500),
                },
            )

        elif request.method == HTTPMethod.GET:
            orders = [
                {
                    "id": f"ORD-{i}",
                    "status": random.choice(["pending", "completed", "cancelled"]),
                }
                for i in range(1000, 1005)
            ]
            return APIResponse(200, {"orders": orders})

        return APIResponse(405, error="Method not allowed")


@CallPyBack(
    observers=[
        api_observer,
        on_call(
            lambda context: print(
                f"🌐 {context.arguments['request'].method.value} {context.arguments['request'].endpoint}"
            )
        ),
        on_success(
            lambda result: event_bus.publish("api.request.completed", result.value)
        ),
        on_failure(
            lambda result: event_bus.publish(
                "api.request.failed", {"error": str(result.exception)}
            )
        ),
    ]
)
def handle_api_request(request: APIRequest) -> Dict[str, Any]:
    """Handle API request with monitoring"""

    start_time = time.time()

    try:
        # Route request to appropriate handler
        if request.endpoint.startswith("/api/users"):
            response = MockAPIHandlers.handle_users(request)
        elif request.endpoint.startswith("/api/products"):
            response = MockAPIHandlers.handle_products(request)
        elif request.endpoint.startswith("/api/orders"):
            response = MockAPIHandlers.handle_orders(request)
        else:
            response = APIResponse(404, error="Endpoint not found")

        # Simulate processing time
        time.sleep(random.uniform(0.01, 0.1))

        response_time = time.time() - start_time

        return {
            "method": request.method.value,
            "endpoint": request.endpoint,
            "status_code": response.status_code,
            "response_time": response_time,
            "response_data": response.data,
            "error": response.error,
            "user_id": request.user_id,
            "status": "completed",
        }

    except Exception as e:
        response_time = time.time() - start_time
        return {
            "method": request.method.value,
            "endpoint": request.endpoint,
            "status_code": 500,
            "response_time": response_time,
            "error": str(e),
            "status": "failed",
        }


class SimpleAPIServer:
    """Simplified API server using CallPyBack plugins"""

    def __init__(self):
        self.event_bus = event_bus
        self.executor = thread_executor
        self.observer = api_observer

        # Start services
        self.executor.start()

        # Setup event handlers
        self.event_bus.subscribe("api.request.completed", self._on_request_completed)
        self.event_bus.subscribe("api.request.failed", self._on_request_failed)

        # Rate limiting (simple in-memory)
        self.rate_limits = {}
        self.rate_limit_window = 60  # 1 minute
        self.rate_limit_max = 100  # 100 requests per minute

    def _on_request_completed(self, message):
        """Handle completed API request"""
        payload = message.payload
        method = payload.get("method", "UNKNOWN")
        endpoint = payload.get("endpoint", "unknown")
        status_code = payload.get("status_code", 500)
        response_time = payload.get("response_time", 0)

        status_icon = "✅" if status_code < 400 else "❌"
        print(
            f"  {status_icon} {method} {endpoint}: {status_code} ({response_time:.3f}s)"
        )

    def _on_request_failed(self, message):
        """Handle failed API request"""
        error = message.payload.get("error", "Unknown error")
        print(f"  ❌ API request failed: {error}")

    def check_rate_limit(self, user_id: str) -> bool:
        """Simple rate limiting check"""
        current_time = time.time()

        if user_id not in self.rate_limits:
            self.rate_limits[user_id] = []

        # Remove requests outside the window
        self.rate_limits[user_id] = [
            req_time
            for req_time in self.rate_limits[user_id]
            if current_time - req_time < self.rate_limit_window
        ]

        # Check if under limit
        if len(self.rate_limits[user_id]) >= self.rate_limit_max:
            return False

        # Add current request
        self.rate_limits[user_id].append(current_time)
        return True

    def create_request(
        self, method: HTTPMethod, endpoint: str, body: str = None, user_id: str = None
    ) -> APIRequest:
        """Create API request object"""

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SimpleAPIClient/1.0",
        }

        if user_id:
            headers["X-User-ID"] = user_id

        return APIRequest(
            method=method,
            endpoint=endpoint,
            headers=headers,
            body=body,
            user_id=user_id,
        )

    def process_request(self, request: APIRequest) -> Dict[str, Any]:
        """Process single API request"""

        # Check rate limiting
        if request.user_id and not self.check_rate_limit(request.user_id):
            return {
                "method": request.method.value,
                "endpoint": request.endpoint,
                "status_code": 429,
                "error": "Rate limit exceeded",
                "status": "rate_limited",
            }

        # Process request
        return handle_api_request(request)

    def simulate_api_load(self, num_requests: int = 50) -> List[Dict[str, Any]]:
        """Simulate API load with multiple concurrent requests"""

        print(f"🌐 Simulating API load with {num_requests} requests...")

        # Create variety of requests
        request_templates = [
            (HTTPMethod.GET, "/api/users"),
            (HTTPMethod.GET, "/api/users/123"),
            (
                HTTPMethod.POST,
                "/api/users",
                '{"name": "John", "email": "john@example.com"}',
            ),
            (HTTPMethod.GET, "/api/products"),
            (HTTPMethod.POST, "/api/products", '{"name": "Product", "price": 29.99}'),
            (HTTPMethod.POST, "/api/orders", '{"items": ["product1"], "total": 50.0}'),
            (HTTPMethod.GET, "/api/users/999"),  # Not found
        ]

        # Submit requests to thread pool
        results = []

        from concurrent.futures import as_completed

        with thread_executor.executor as executor:
            # Submit all requests
            futures = []
            for i in range(num_requests):
                template = random.choice(request_templates)
                method, endpoint = template[0], template[1]
                body = template[2] if len(template) > 2 else None
                user_id = f"user_{random.randint(1, 10)}"

                request = self.create_request(method, endpoint, body, user_id)
                future = executor.submit(self.process_request, request)
                futures.append(future)

            # Collect results
            for future in as_completed(futures, timeout=30):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append({"error": str(e), "status": "timeout"})

        return results

    def get_api_metrics(self) -> Dict[str, Any]:
        """Get API performance metrics"""

        # Calculate endpoint performance
        endpoint_performance = {}
        for endpoint, stats in self.observer.endpoint_stats.items():
            if stats["requests"] > 0:
                avg_response_time = stats["total_time"] / stats["requests"]
                error_rate = stats["errors"] / stats["requests"]
                endpoint_performance[endpoint] = {
                    "requests": stats["requests"],
                    "avg_response_time": avg_response_time,
                    "error_rate": error_rate,
                }

        # Overall metrics
        avg_response_time = (
            self.observer.total_response_time / self.observer.total_requests
            if self.observer.total_requests > 0
            else 0
        )

        success_rate = (self.observer.total_requests - self.observer.errors) / max(
            self.observer.total_requests, 1
        )

        return {
            "total_requests": self.observer.total_requests,
            "total_errors": self.observer.errors,
            "success_rate": success_rate,
            "avg_response_time": avg_response_time,
            "status_code_distribution": self.observer.status_codes,
            "endpoint_performance": endpoint_performance,
            "active_rate_limits": len(self.rate_limits),
        }

    def shutdown(self):
        """Clean shutdown"""
        self.executor.stop()


def main():
    """Demo the simplified API server"""
    api_server = SimpleAPIServer()

    try:
        # Test individual API calls
        print("🌐 Testing individual API endpoints...")

        test_requests = [
            (HTTPMethod.GET, "/api/users"),
            (
                HTTPMethod.POST,
                "/api/users",
                '{"name": "Alice", "email": "alice@example.com"}',
            ),
            (HTTPMethod.GET, "/api/users/123"),
            (HTTPMethod.GET, "/api/products"),
            (HTTPMethod.POST, "/api/orders", '{"items": ["product1", "product2"]}'),
            (HTTPMethod.GET, "/api/users/999"),  # Not found
        ]

        for method, endpoint, *body in test_requests:
            request_body = body[0] if body else None
            request = api_server.create_request(
                method, endpoint, request_body, "test_user"
            )
            result = api_server.process_request(request)

            status_icon = "✅" if result.get("status_code", 500) < 400 else "❌"
            print(
                f"  {status_icon} {method.value} {endpoint}: {result.get('status_code')}"
            )

        # Simulate high load
        print(f"\n⚡ Simulating high API load...")
        load_results = api_server.simulate_api_load(30)

        # Analyze results
        status_codes = {}
        for result in load_results:
            code = result.get("status_code", 500)
            status_codes[code] = status_codes.get(code, 0) + 1

        print(f"📊 Load test results:")
        for code, count in sorted(status_codes.items()):
            print(f"  {code}: {count} requests")

        # Show detailed metrics
        metrics = api_server.get_api_metrics()
        print(f"\n📈 API Performance Metrics:")
        print(f"  Total requests: {metrics['total_requests']}")
        print(f"  Success rate: {metrics['success_rate']:.1%}")
        print(f"  Avg response time: {metrics['avg_response_time']:.3f}s")
        print(f"  Total errors: {metrics['total_errors']}")

        print(f"\n🎯 Top endpoints:")
        for endpoint, perf in list(metrics["endpoint_performance"].items())[:3]:
            print(
                f"  {endpoint}: {perf['requests']} requests, {perf['avg_response_time']:.3f}s avg"
            )

    finally:
        api_server.shutdown()


if __name__ == "__main__":
    main()
