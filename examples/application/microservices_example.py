#!/usr/bin/env python3
"""
Microservices Monitoring Example
Demonstrates monitoring microservices with CallPyBack for:
- Service mesh monitoring
- Distributed tracing
- Circuit breaker patterns
- Service health monitoring
- Inter-service communication tracking
"""

import random
import threading
import time
import uuid
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

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


class ServiceStatus(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    DOWN = "DOWN"


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class ServiceCall:
    service_name: str
    operation: str
    caller_service: str
    trace_id: str
    span_id: str
    parent_span: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceSpan:
    trace_id: str
    span_id: str
    parent_span: Optional[str]
    service_name: str
    operation: str
    start_time: float
    end_time: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)


class ServiceMeshObserver(BaseObserver):
    """Monitor service mesh interactions and health"""

    def __init__(self):
        super().__init__(priority=95, name="ServiceMesh")
        self.service_metrics = defaultdict(
            lambda: {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "total_latency": 0,
                "latencies": deque(maxlen=100),
                "error_rates": deque(maxlen=50),
                "last_request_time": None,
            }
        )
        self.service_dependencies = defaultdict(set)  # service -> set of dependencies
        self.service_callers = defaultdict(set)  # service -> set of callers
        self.service_topology = {}
        self.lock = threading.Lock()

    def update(self, context: ExecutionContext) -> None:
        if context.state != ExecutionState.COMPLETED:
            return

        service_call = context.arguments.get("service_call")
        if not service_call:
            return

        with self.lock:
            service_name = service_call.service_name
            caller_service = service_call.caller_service

            # Update service metrics
            metrics = self.service_metrics[service_name]
            metrics["total_requests"] += 1
            metrics["last_request_time"] = time.time()

            if context.result:
                execution_time = getattr(context.result, "execution_time", 0)
                metrics["total_latency"] += execution_time
                metrics["latencies"].append(execution_time)

                if context.is_successful:
                    metrics["successful_requests"] += 1
                else:
                    metrics["failed_requests"] += 1

                # Track error rates over time (calculate every 10 requests)
                if metrics["total_requests"] % 10 == 0:
                    recent_error_rate = (
                        metrics["failed_requests"] / metrics["total_requests"]
                    ) * 100
                    metrics["error_rates"].append(recent_error_rate)

            # Track service dependencies
            if caller_service != "external":
                self.service_dependencies[caller_service].add(service_name)
                self.service_callers[service_name].add(caller_service)

    def get_service_health_report(self):
        """Generate service health report"""
        with self.lock:
            report = {}
            current_time = time.time()

            for service_name, metrics in self.service_metrics.items():
                # Calculate health metrics
                total_requests = metrics["total_requests"]
                if total_requests == 0:
                    continue

                error_rate = (metrics["failed_requests"] / total_requests) * 100
                avg_latency = metrics["total_latency"] / total_requests

                # Calculate percentiles
                latencies = sorted(metrics["latencies"])
                p95_latency = latencies[int(len(latencies) * 0.95)] if latencies else 0
                p99_latency = latencies[int(len(latencies) * 0.99)] if latencies else 0

                # Determine health status
                last_request_age = (
                    current_time - metrics["last_request_time"]
                    if metrics["last_request_time"]
                    else 0
                )

                if last_request_age > 300:  # No requests in 5 minutes
                    health_status = ServiceStatus.DOWN
                elif error_rate > 20:
                    health_status = ServiceStatus.UNHEALTHY
                elif error_rate > 5 or avg_latency > 1.0:
                    health_status = ServiceStatus.DEGRADED
                else:
                    health_status = ServiceStatus.HEALTHY

                report[service_name] = {
                    "status": health_status.value,
                    "total_requests": total_requests,
                    "error_rate": f"{error_rate:.1f}%",
                    "avg_latency": f"{avg_latency:.3f}s",
                    "p95_latency": f"{p95_latency:.3f}s",
                    "p99_latency": f"{p99_latency:.3f}s",
                    "last_request_age": f"{last_request_age:.1f}s",
                    "dependencies": list(
                        self.service_dependencies.get(service_name, [])
                    ),
                    "callers": list(self.service_callers.get(service_name, [])),
                }

            return report

    def get_service_topology(self):
        """Get service dependency topology"""
        with self.lock:
            return {
                "dependencies": {
                    service: list(deps)
                    for service, deps in self.service_dependencies.items()
                },
                "callers": {
                    service: list(callers)
                    for service, callers in self.service_callers.items()
                },
            }

    def detect_circular_dependencies(self):
        """Detect circular dependencies in service topology"""

        def has_cycle(graph, start, visited, rec_stack):
            visited[start] = True
            rec_stack[start] = True

            for neighbor in graph.get(start, []):
                if not visited.get(neighbor, False):
                    if has_cycle(graph, neighbor, visited, rec_stack):
                        return True
                elif rec_stack.get(neighbor, False):
                    return True

            rec_stack[start] = False
            return False

        with self.lock:
            visited = {}
            rec_stack = {}
            cycles = []

            for service in self.service_dependencies:
                if not visited.get(service, False):
                    if has_cycle(
                        self.service_dependencies, service, visited, rec_stack
                    ):
                        cycles.append(service)

            return cycles


class DistributedTracingObserver(BaseObserver):
    """Monitor distributed traces across services"""

    def __init__(self):
        super().__init__(priority=90, name="DistributedTracing")
        self.active_traces = defaultdict(list)  # trace_id -> list of spans
        self.completed_traces = deque(maxlen=100)  # Recently completed traces
        self.trace_metrics = {
            "total_traces": 0,
            "completed_traces": 0,
            "failed_traces": 0,
            "avg_trace_duration": 0,
            "avg_spans_per_trace": 0,
        }
        self.lock = threading.Lock()

    def update(self, context: ExecutionContext) -> None:
        service_call = context.arguments.get("service_call")
        if not service_call:
            return

        with self.lock:
            trace_id = service_call.trace_id
            span_id = service_call.span_id

            if context.state == ExecutionState.PRE_EXECUTION:
                # Start span
                span = TraceSpan(
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span=service_call.parent_span,
                    service_name=service_call.service_name,
                    operation=service_call.operation,
                    start_time=context.timestamp,
                    tags={"caller": service_call.caller_service},
                )
                self.active_traces[trace_id].append(span)

            elif context.state == ExecutionState.COMPLETED:
                # Complete span
                for span in self.active_traces[trace_id]:
                    if span.span_id == span_id:
                        span.end_time = context.timestamp
                        span.success = context.is_successful
                        if not context.is_successful and context.result:
                            span.error_message = str(
                                getattr(context.result, "exception", "Unknown error")
                            )
                        break

                # Check if trace is complete (all spans have end_time)
                trace_spans = self.active_traces[trace_id]
                if all(span.end_time is not None for span in trace_spans):
                    self._complete_trace(trace_id, trace_spans)

    def _complete_trace(self, trace_id: str, spans: List[TraceSpan]):
        """Mark trace as complete and calculate metrics"""
        trace_start = min(span.start_time for span in spans)
        trace_end = max(span.end_time for span in spans)
        trace_duration = trace_end - trace_start

        trace_success = all(span.success for span in spans)

        trace_summary = {
            "trace_id": trace_id,
            "duration": trace_duration,
            "span_count": len(spans),
            "services_involved": len(set(span.service_name for span in spans)),
            "success": trace_success,
            "spans": spans.copy(),
        }

        self.completed_traces.append(trace_summary)
        del self.active_traces[trace_id]

        # Update metrics
        self.trace_metrics["total_traces"] += 1
        if trace_success:
            self.trace_metrics["completed_traces"] += 1
        else:
            self.trace_metrics["failed_traces"] += 1

        # Recalculate averages
        total_completed = len(self.completed_traces)
        if total_completed > 0:
            self.trace_metrics["avg_trace_duration"] = (
                sum(t["duration"] for t in self.completed_traces) / total_completed
            )
            self.trace_metrics["avg_spans_per_trace"] = (
                sum(t["span_count"] for t in self.completed_traces) / total_completed
            )

        print(
            f"🔗 Trace completed: {trace_id} ({trace_duration:.3f}s, {len(spans)} spans, {'✅' if trace_success else '❌'})"
        )

    def get_trace_analysis(self):
        """Get distributed tracing analysis"""
        with self.lock:
            analysis = {
                "metrics": self.trace_metrics.copy(),
                "active_traces": len(self.active_traces),
                "recent_traces": [],
            }

            # Add recent trace summaries
            for trace in list(self.completed_traces)[-10:]:  # Last 10 traces
                analysis["recent_traces"].append(
                    {
                        "trace_id": trace["trace_id"][:8]
                        + "...",  # Shortened for display
                        "duration": f"{trace['duration']:.3f}s",
                        "spans": trace["span_count"],
                        "services": trace["services_involved"],
                        "success": trace["success"],
                    }
                )

            return analysis

    def get_service_call_patterns(self):
        """Analyze service call patterns from traces"""
        with self.lock:
            patterns = defaultdict(int)
            service_pairs = defaultdict(int)

            for trace in self.completed_traces:
                spans = trace["spans"]

                # Track service call sequences
                for i, span in enumerate(spans):
                    if span.parent_span:
                        # Find parent span
                        parent = next(
                            (s for s in spans if s.span_id == span.parent_span), None
                        )
                        if parent:
                            service_pair = (
                                f"{parent.service_name} -> {span.service_name}"
                            )
                            service_pairs[service_pair] += 1

                            # Track operation patterns
                            pattern = f"{parent.service_name}.{parent.operation} -> {span.service_name}.{span.operation}"
                            patterns[pattern] += 1

            return {
                "service_call_patterns": dict(patterns),
                "service_pairs": dict(service_pairs),
            }


class CircuitBreakerObserver(BaseObserver):
    """Implement circuit breaker pattern monitoring"""

    def __init__(self, failure_threshold: int = 5, timeout: float = 30.0):
        super().__init__(priority=85, name="CircuitBreaker")
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.circuit_states = defaultdict(
            lambda: {
                "state": CircuitState.CLOSED,
                "failure_count": 0,
                "last_failure_time": None,
                "success_count": 0,
            }
        )
        self.lock = threading.Lock()

    def update(self, context: ExecutionContext) -> None:
        service_call = context.arguments.get("service_call")
        if not service_call or context.state != ExecutionState.COMPLETED:
            return

        with self.lock:
            service_name = service_call.service_name
            circuit = self.circuit_states[service_name]
            current_time = time.time()

            # Check if we should transition from OPEN to HALF_OPEN
            if (
                circuit["state"] == CircuitState.OPEN
                and circuit["last_failure_time"]
                and current_time - circuit["last_failure_time"] > self.timeout
            ):
                circuit["state"] = CircuitState.HALF_OPEN
                circuit["success_count"] = 0
                print(f"🔄 Circuit breaker HALF_OPEN for {service_name}")

            if context.is_successful:
                if circuit["state"] == CircuitState.HALF_OPEN:
                    circuit["success_count"] += 1
                    if circuit["success_count"] >= 3:  # 3 successful calls to close
                        circuit["state"] = CircuitState.CLOSED
                        circuit["failure_count"] = 0
                        print(f"✅ Circuit breaker CLOSED for {service_name}")
                elif circuit["state"] == CircuitState.CLOSED:
                    circuit["failure_count"] = max(
                        0, circuit["failure_count"] - 1
                    )  # Decay failures
            else:
                circuit["failure_count"] += 1
                circuit["last_failure_time"] = current_time

                if circuit["state"] in [CircuitState.CLOSED, CircuitState.HALF_OPEN]:
                    if circuit["failure_count"] >= self.failure_threshold:
                        circuit["state"] = CircuitState.OPEN
                        print(
                            f"🚨 Circuit breaker OPEN for {service_name} (failures: {circuit['failure_count']})"
                        )

    def get_circuit_status(self):
        """Get current circuit breaker status"""
        with self.lock:
            status = {}
            current_time = time.time()

            for service_name, circuit in self.circuit_states.items():
                time_since_failure = (
                    current_time - circuit["last_failure_time"]
                    if circuit["last_failure_time"]
                    else None
                )

                status[service_name] = {
                    "state": circuit["state"].value,
                    "failure_count": circuit["failure_count"],
                    "time_since_last_failure": (
                        f"{time_since_failure:.1f}s" if time_since_failure else "N/A"
                    ),
                    "can_accept_requests": circuit["state"] != CircuitState.OPEN,
                }

            return status

    def should_allow_request(self, service_name: str) -> bool:
        """Check if request should be allowed through circuit breaker"""
        with self.lock:
            circuit = self.circuit_states[service_name]
            return circuit["state"] != CircuitState.OPEN


# Set up monitoring
service_mesh_monitor = ServiceMeshObserver()
tracing_monitor = DistributedTracingObserver()
circuit_breaker = CircuitBreakerObserver(failure_threshold=3, timeout=10.0)

# Error handler for service calls
service_error_handler = DefaultErrorHandler(
    default_return={
        "status": "error",
        "error": "Service unavailable",
        "service_down": True,
    }
)


class MockMicroservice:
    """Mock microservice for simulation"""

    def __init__(self, name: str, base_latency: float = 0.1, error_rate: float = 0.05):
        self.name = name
        self.base_latency = base_latency
        self.error_rate = error_rate
        self.request_count = 0

    def handle_request(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate handling a service request"""
        self.request_count += 1

        # Simulate varying latency
        latency = self.base_latency + random.uniform(0, self.base_latency)
        time.sleep(latency)

        # Simulate errors
        if random.random() < self.error_rate:
            error_types = [
                "Database connection failed",
                "Timeout occurred",
                "Invalid request data",
                "Resource not found",
                "Rate limit exceeded",
            ]
            raise RuntimeError(f"{self.name} error: {random.choice(error_types)}")

        # Return successful response
        return {
            "service": self.name,
            "operation": operation,
            "request_id": f"{self.name}_{self.request_count}",
            "timestamp": time.time(),
            "data": f"Response from {self.name} for {operation}",
            "status": "success",
        }


# Create mock services
services = {
    "api-gateway": MockMicroservice("api-gateway", base_latency=0.02, error_rate=0.03),
    "auth-service": MockMicroservice(
        "auth-service", base_latency=0.05, error_rate=0.08
    ),
    "user-service": MockMicroservice("user-service", base_latency=0.1, error_rate=0.05),
    "order-service": MockMicroservice(
        "order-service", base_latency=0.15, error_rate=0.1
    ),
    "payment-service": MockMicroservice(
        "payment-service", base_latency=0.2, error_rate=0.12
    ),
    "inventory-service": MockMicroservice(
        "inventory-service", base_latency=0.08, error_rate=0.06
    ),
    "notification-service": MockMicroservice(
        "notification-service", base_latency=0.03, error_rate=0.04
    ),
    "analytics-service": MockMicroservice(
        "analytics-service", base_latency=0.06, error_rate=0.02
    ),
}


@CallPyBack(
    observers=[
        service_mesh_monitor,
        tracing_monitor,
        circuit_breaker,
        on_call(
            lambda context: print(
                f"🌐 Service call: {context.arguments['service_call'].caller_service} -> {context.arguments['service_call'].service_name}.{context.arguments['service_call'].operation}"
            )
        ),
        on_failure(lambda result: print(f"❌ Service call failed: {result.exception}")),
    ],
    error_handler=service_error_handler,
    exception_classes=(RuntimeError, ConnectionError, TimeoutError),
)
def call_microservice(service_call: ServiceCall) -> Dict[str, Any]:
    """Call a microservice with monitoring"""

    # Check circuit breaker
    if not circuit_breaker.should_allow_request(service_call.service_name):
        raise RuntimeError(f"Circuit breaker OPEN for {service_call.service_name}")

    # Get the service
    service = services.get(service_call.service_name)
    if not service:
        raise RuntimeError(f"Service {service_call.service_name} not found")

    # Handle the request
    response = service.handle_request(service_call.operation, service_call.payload)

    return {
        "service_call_id": f"{service_call.trace_id}:{service_call.span_id}",
        "response": response,
        "service_name": service_call.service_name,
        "operation": service_call.operation,
    }


def create_service_call(
    service_name: str,
    operation: str,
    caller_service: str,
    trace_id: str = None,
    parent_span: str = None,
) -> ServiceCall:
    """Create a service call with tracing information"""

    if not trace_id:
        trace_id = str(uuid.uuid4())[:8]

    span_id = f"span_{service_name}_{uuid.uuid4().hex[:8]}"

    return ServiceCall(
        service_name=service_name,
        operation=operation,
        caller_service=caller_service,
        trace_id=trace_id,
        span_id=span_id,
        parent_span=parent_span,
        headers={"content-type": "application/json"},
        payload={"timestamp": time.time(), "request_data": f"data_for_{operation}"},
    )


def simulate_user_workflow(user_id: str) -> Dict[str, Any]:
    """Simulate a complete user workflow across multiple services"""

    trace_id = f"user_workflow_{user_id}_{uuid.uuid4().hex[:8]}"
    results = {}

    try:
        # 1. API Gateway - Route request
        gateway_call = create_service_call(
            "api-gateway", "route_request", "external", trace_id
        )
        gateway_response = call_microservice(gateway_call)
        results["gateway"] = gateway_response

        # 2. Auth Service - Validate user
        auth_call = create_service_call(
            "auth-service",
            "validate_token",
            "api-gateway",
            trace_id,
            gateway_call.span_id,
        )
        auth_response = call_microservice(auth_call)
        results["auth"] = auth_response

        # 3. User Service - Get user profile
        user_call = create_service_call(
            "user-service", "get_profile", "api-gateway", trace_id, auth_call.span_id
        )
        user_call.payload["user_id"] = user_id
        user_response = call_microservice(user_call)
        results["user"] = user_response

        # 4. Order Service - Create order
        order_call = create_service_call(
            "order-service", "create_order", "user-service", trace_id, user_call.span_id
        )
        order_call.payload.update({"user_id": user_id, "items": ["item1", "item2"]})
        order_response = call_microservice(order_call)
        results["order"] = order_response

        # 5. Inventory Service - Check availability
        inventory_call = create_service_call(
            "inventory-service",
            "check_availability",
            "order-service",
            trace_id,
            order_call.span_id,
        )
        inventory_response = call_microservice(inventory_call)
        results["inventory"] = inventory_response

        # 6. Payment Service - Process payment
        payment_call = create_service_call(
            "payment-service",
            "process_payment",
            "order-service",
            trace_id,
            inventory_call.span_id,
        )
        payment_call.payload.update({"amount": 99.99, "currency": "USD"})
        payment_response = call_microservice(payment_call)
        results["payment"] = payment_response

        # 7. Notification Service - Send confirmation
        notification_call = create_service_call(
            "notification-service",
            "send_email",
            "payment-service",
            trace_id,
            payment_call.span_id,
        )
        notification_call.payload.update(
            {"user_id": user_id, "template": "order_confirmation"}
        )
        notification_response = call_microservice(notification_call)
        results["notification"] = notification_response

        # 8. Analytics Service - Track event
        analytics_call = create_service_call(
            "analytics-service",
            "track_event",
            "notification-service",
            trace_id,
            notification_call.span_id,
        )
        analytics_call.payload.update({"event": "order_completed", "user_id": user_id})
        analytics_response = call_microservice(analytics_call)
        results["analytics"] = analytics_response

        return {
            "trace_id": trace_id,
            "user_id": user_id,
            "status": "completed",
            "services_called": len(results),
            "results": results,
        }

    except Exception as e:
        return {
            "trace_id": trace_id,
            "user_id": user_id,
            "status": "failed",
            "error": str(e),
            "partial_results": results,
        }


def simulate_microservices_load():
    """Simulate realistic microservices load"""

    print("🚀 Starting Microservices Simulation")
    print("=" * 60)

    # Individual service calls
    print("📡 Executing individual service calls...")
    individual_calls = [
        ("api-gateway", "health_check"),
        ("auth-service", "validate_token"),
        ("user-service", "get_profile"),
        ("order-service", "list_orders"),
        ("inventory-service", "check_stock"),
        ("payment-service", "validate_card"),
        ("notification-service", "send_sms"),
        ("analytics-service", "log_event"),
    ]

    for i in range(30):  # 30 individual calls
        service_name, operation = random.choice(individual_calls)
        service_call = create_service_call(service_name, operation, "test_client")

        try:
            response = call_microservice(service_call)
            print(f"  ✅ {service_name}.{operation}")
        except Exception as e:
            print(f"  ❌ {service_name}.{operation}: {e}")

        time.sleep(random.uniform(0.01, 0.05))

    # Concurrent user workflows
    print(f"\n👥 Executing concurrent user workflows...")
    user_workflows = []

    with ThreadPoolExecutor(
        max_workers=5, thread_name_prefix="UserWorkflow"
    ) as executor:
        # Submit workflows for different users
        futures = []
        for i in range(15):  # 15 concurrent users
            user_id = f"user_{i:03d}"
            future = executor.submit(simulate_user_workflow, user_id)
            futures.append(future)

        # Collect results
        for future in as_completed(futures, timeout=60):
            try:
                workflow_result = future.result()
                user_workflows.append(workflow_result)
                status_icon = "✅" if workflow_result["status"] == "completed" else "❌"
                print(
                    f"  {status_icon} User workflow {workflow_result['user_id']}: {workflow_result['status']}"
                )
            except Exception as e:
                print(f"  ❌ Workflow failed: {e}")

    # High-load simulation
    print(f"\n⚡ High-load simulation...")
    high_load_calls = []

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="HighLoad") as executor:
        futures = []

        # Generate high load across all services
        for _ in range(50):
            service_name = random.choice(list(services.keys()))
            operations = ["read_operation", "write_operation", "query_operation"]
            operation = random.choice(operations)

            service_call = create_service_call(service_name, operation, "load_test")
            future = executor.submit(call_microservice, service_call)
            futures.append((service_name, operation, future))

        # Collect high-load results
        for service_name, operation, future in futures:
            try:
                result = future.result(timeout=5)
                high_load_calls.append({"service": service_name, "success": True})
            except Exception:
                high_load_calls.append({"service": service_name, "success": False})

    print(f"  Completed {len(high_load_calls)} high-load calls")

    print(f"\n🏁 Microservices simulation completed")

    # Generate comprehensive analysis
    print("\n" + "=" * 80)
    print("📊 MICROSERVICES MONITORING ANALYSIS")
    print("=" * 80)

    # Service health report
    health_report = service_mesh_monitor.get_service_health_report()
    print(f"\n🏥 Service Health Status:")
    for service_name, health in health_report.items():
        status_icon = {
            "HEALTHY": "🟢",
            "DEGRADED": "🟡",
            "UNHEALTHY": "🔴",
            "DOWN": "⚫",
        }.get(health["status"], "❓")

        print(f"  {status_icon} {service_name}:")
        print(f"    Status: {health['status']}")
        print(f"    Requests: {health['total_requests']}")
        print(f"    Error Rate: {health['error_rate']}")
        print(f"    Avg Latency: {health['avg_latency']}")
        print(f"    P95 Latency: {health['p95_latency']}")
        if health["dependencies"]:
            print(f"    Dependencies: {', '.join(health['dependencies'])}")

    # Service topology
    topology = service_mesh_monitor.get_service_topology()
    print(f"\n🕸️  Service Dependency Topology:")
    for service, dependencies in topology["dependencies"].items():
        if dependencies:
            print(f"  {service} depends on: {', '.join(dependencies)}")

    # Check for circular dependencies
    circular_deps = service_mesh_monitor.detect_circular_dependencies()
    if circular_deps:
        print(f"\n⚠️  Circular dependencies detected in: {', '.join(circular_deps)}")
    else:
        print(f"\n✅ No circular dependencies detected")

    # Distributed tracing analysis
    trace_analysis = tracing_monitor.get_trace_analysis()
    print(f"\n🔗 Distributed Tracing Analysis:")
    print(f"  Total Traces: {trace_analysis['metrics']['total_traces']}")
    print(f"  Completed: {trace_analysis['metrics']['completed_traces']}")
    print(f"  Failed: {trace_analysis['metrics']['failed_traces']}")
    print(f"  Avg Duration: {trace_analysis['metrics']['avg_trace_duration']:.3f}s")
    print(f"  Avg Spans/Trace: {trace_analysis['metrics']['avg_spans_per_trace']:.1f}")
    print(f"  Active Traces: {trace_analysis['active_traces']}")

    if trace_analysis["recent_traces"]:
        print(f"\n  Recent Traces:")
        for trace in trace_analysis["recent_traces"][-5:]:
            status_icon = "✅" if trace["success"] else "❌"
            print(
                f"    {status_icon} {trace['trace_id']}: {trace['duration']}, {trace['spans']} spans, {trace['services']} services"
            )

    # Service call patterns
    call_patterns = tracing_monitor.get_service_call_patterns()
    print(f"\n📞 Service Call Patterns:")
    print(f"  Top service pairs:")
    sorted_pairs = sorted(
        call_patterns["service_pairs"].items(), key=lambda x: x[1], reverse=True
    )
    for pair, count in sorted_pairs[:5]:
        print(f"    {pair}: {count} calls")

    # Circuit breaker status
    circuit_status = circuit_breaker.get_circuit_status()
    print(f"\n🔌 Circuit Breaker Status:")
    for service_name, status in circuit_status.items():
        state_icon = {"CLOSED": "🟢", "HALF_OPEN": "🟡", "OPEN": "🔴"}.get(
            status["state"], "❓"
        )

        print(f"  {state_icon} {service_name}:")
        print(f"    State: {status['state']}")
        print(f"    Failures: {status['failure_count']}")
        print(
            f"    Can Accept Requests: {'Yes' if status['can_accept_requests'] else 'No'}"
        )
        if status["time_since_last_failure"] != "N/A":
            print(f"    Last Failure: {status['time_since_last_failure']} ago")

    # Workflow success analysis
    successful_workflows = sum(1 for w in user_workflows if w["status"] == "completed")
    workflow_success_rate = (
        (successful_workflows / len(user_workflows)) * 100 if user_workflows else 0
    )

    print(f"\n📋 Workflow Analysis:")
    print(f"  Total User Workflows: {len(user_workflows)}")
    print(f"  Successful: {successful_workflows}")
    print(f"  Success Rate: {workflow_success_rate:.1f}%")

    # High-load analysis
    high_load_success = sum(1 for call in high_load_calls if call["success"])
    high_load_success_rate = (
        (high_load_success / len(high_load_calls)) * 100 if high_load_calls else 0
    )

    print(f"\n⚡ High-Load Analysis:")
    print(f"  Total Calls: {len(high_load_calls)}")
    print(f"  Successful: {high_load_success}")
    print(f"  Success Rate: {high_load_success_rate:.1f}%")


if __name__ == "__main__":
    simulate_microservices_load()
