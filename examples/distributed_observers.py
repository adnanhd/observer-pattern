#!/usr/bin/env python3
"""
Distributed Systems Example
Demonstrates microservices monitoring with distributed tracing and service mesh patterns.
"""

import random
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from callpyback import CallPyBack
from callpyback.core.state_machine import ExecutionState
from callpyback.observers.base import BaseObserver


class ServiceMeshObserver(BaseObserver):
    """Service mesh monitoring for microservices architecture."""

    def __init__(self):
        super().__init__(priority=85, name="ServiceMesh")
        self.service_calls = []
        self.service_topology = defaultdict(set)  # service -> set of called services
        self.service_metrics = defaultdict(
            lambda: {
                "requests": 0,
                "successes": 0,
                "failures": 0,
                "total_latency": 0,
                "latencies": [],
            }
        )
        self.cross_service_calls = defaultdict(int)
        self.lock = threading.Lock()

    def update(self, context):
        """Monitor service mesh interactions."""
        if context.state == ExecutionState.COMPLETED:
            with self.lock:
                service_name = context.arguments.get("service", "unknown")
                caller_service = context.arguments.get("caller_service", "client")
                operation = context.arguments.get("operation", "unknown")

                # Record service call
                call_record = {
                    "service": service_name,
                    "caller": caller_service,
                    "operation": operation,
                    "timestamp": context.timestamp,
                    "success": context.is_successful,
                    "latency": (
                        getattr(context.result, "execution_time", 0)
                        if context.result
                        else 0
                    ),
                    "trace_id": context.arguments.get("trace_id", "unknown"),
                }

                self.service_calls.append(call_record)

                # Update service topology
                if caller_service != "client":
                    self.service_topology[caller_service].add(service_name)

                # Update service metrics
                metrics = self.service_metrics[service_name]
                metrics["requests"] += 1

                if context.is_successful:
                    metrics["successes"] += 1
                else:
                    metrics["failures"] += 1

                if call_record["latency"] > 0:
                    metrics["latencies"].append(call_record["latency"])
                    metrics["total_latency"] += call_record["latency"]

                # Track cross-service communication
                call_key = f"{caller_service}->{service_name}"
                self.cross_service_calls[call_key] += 1

                # Service health alerts
                error_rate = metrics["failures"] / max(metrics["requests"], 1)
                if metrics["requests"] >= 10 and error_rate > 0.2:
                    print(
                        f"🚨 SERVICE MESH ALERT: {service_name} error rate: {error_rate*100:.1f}%"
                    )

    def get_service_mesh_metrics(self):
        """Generate service mesh analysis."""
        with self.lock:
            mesh_metrics = {}

            for service, metrics in self.service_metrics.items():
                latencies = metrics["latencies"]

                if latencies:
                    latencies_sorted = sorted(latencies)
                    p50 = latencies_sorted[len(latencies_sorted) // 2]
                    p95 = latencies_sorted[int(0.95 * len(latencies_sorted))]
                    p99 = latencies_sorted[int(0.99 * len(latencies_sorted))]
                    avg_latency = metrics["total_latency"] / len(latencies)
                else:
                    p50 = p95 = p99 = avg_latency = 0

                mesh_metrics[service] = {
                    "total_requests": metrics["requests"],
                    "success_rate": (metrics["successes"] / max(metrics["requests"], 1))
                    * 100,
                    "error_rate": (metrics["failures"] / max(metrics["requests"], 1))
                    * 100,
                    "avg_latency_ms": avg_latency * 1000,
                    "p50_latency_ms": p50 * 1000,
                    "p95_latency_ms": p95 * 1000,
                    "p99_latency_ms": p99 * 1000,
                    "health_status": (
                        "healthy"
                        if (metrics["failures"] / max(metrics["requests"], 1)) < 0.1
                        else "degraded"
                    ),
                }

            return {
                "services": mesh_metrics,
                "topology": {
                    service: list(deps)
                    for service, deps in self.service_topology.items()
                },
                "communication_patterns": dict(self.cross_service_calls),
                "total_calls": len(self.service_calls),
            }


class DistributedTracingObserver(BaseObserver):
    """Distributed tracing for request flow monitoring."""

    def __init__(self):
        super().__init__(priority=80, name="DistributedTracing")
        self.traces = defaultdict(list)
        self.active_spans = {}
        self.trace_metrics = defaultdict(
            lambda: {"total_spans": 0, "total_duration": 0, "error_spans": 0}
        )
        self.lock = threading.Lock()

    def update(self, context):
        """Track distributed traces across services."""
        trace_id = context.arguments.get("trace_id", f"trace_{time.time()}")
        span_id = context.arguments.get("span_id", f"span_{random.randint(1000, 9999)}")

        with self.lock:
            if context.state == ExecutionState.PRE_EXECUTION:
                # Start span
                span = {
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "service": context.arguments.get("service", "unknown"),
                    "operation": context.function_signature.name,
                    "start_time": context.timestamp,
                    "parent_span": context.arguments.get("parent_span"),
                    "caller_service": context.arguments.get("caller_service", "client"),
                }
                self.active_spans[span_id] = span

            elif context.state == ExecutionState.COMPLETED:
                # Complete span
                if span_id in self.active_spans:
                    span = self.active_spans[span_id]
                    span.update(
                        {
                            "end_time": context.timestamp,
                            "duration": (
                                getattr(context.result, "execution_time", 0)
                                if context.result
                                else 0
                            ),
                            "success": context.is_successful,
                            "error": (
                                str(context.result.exception)
                                if context.is_failed
                                else None
                            ),
                            "status_code": "200" if context.is_successful else "500",
                        }
                    )

                    self.traces[trace_id].append(span)

                    # Update trace metrics
                    metrics = self.trace_metrics[trace_id]
                    metrics["total_spans"] += 1
                    metrics["total_duration"] += span["duration"]
                    if not span["success"]:
                        metrics["error_spans"] += 1

                    del self.active_spans[span_id]

    def get_trace_analysis(self):
        """Analyze distributed traces."""
        with self.lock:
            analysis = {
                "total_traces": len(self.traces),
                "completed_spans": sum(len(spans) for spans in self.traces.values()),
                "active_spans": len(self.active_spans),
                "trace_summaries": [],
            }

            for trace_id, spans in self.traces.items():
                if spans:
                    total_duration = max(span["end_time"] for span in spans) - min(
                        span["start_time"] for span in spans
                    )
                    error_count = sum(1 for span in spans if not span["success"])
                    services_involved = len(set(span["service"] for span in spans))

                    analysis["trace_summaries"].append(
                        {
                            "trace_id": trace_id,
                            "total_duration": total_duration,
                            "span_count": len(spans),
                            "services_involved": services_involved,
                            "error_count": error_count,
                            "success": error_count == 0,
                        }
                    )

            return analysis


# Setup distributed monitoring
service_mesh = ServiceMeshObserver()
distributed_tracing = DistributedTracingObserver()


@CallPyBack(
    observers=[service_mesh, distributed_tracing],
    exception_classes=(ConnectionError, TimeoutError, ValueError, RuntimeError),
    default_return={"status": "service_unavailable", "error": True},
)
def microservice_call(service, operation, **kwargs):
    """Simulate microservice call with realistic behavior."""

    # Service-specific behavior simulation
    if service == "api_gateway":
        if operation == "route_request":
            time.sleep(random.uniform(0.001, 0.005))  # Very fast routing
            if random.random() < 0.01:  # 1% error rate
                raise RuntimeError("Gateway routing error")
            return {
                "status": "routed",
                "target_service": kwargs.get("target_service"),
            }

    elif service == "auth_service":
        if operation == "validate_token":
            time.sleep(random.uniform(0.01, 0.03))
            if random.random() < 0.03:  # 3% error rate
                raise ValueError("Invalid authentication token")
            return {"status": "valid", "user_id": kwargs.get("user_id", "user123")}

        elif operation == "refresh_token":
            time.sleep(random.uniform(0.02, 0.05))
            if random.random() < 0.05:  # 5% error rate
                raise ConnectionError("Auth service database unavailable")
            return {
                "status": "refreshed",
                "new_token": "token_" + str(random.randint(1000, 9999)),
            }

    elif service == "user_service":
        if operation == "get_profile":
            time.sleep(random.uniform(0.02, 0.06))
            if random.random() < 0.04:  # 4% error rate
                raise TimeoutError("Database query timeout")
            return {
                "status": "success",
                "profile": {"user_id": kwargs.get("user_id"), "name": "User Name"},
            }

        elif operation == "update_profile":
            time.sleep(random.uniform(0.05, 0.12))
            if random.random() < 0.08:  # 8% error rate
                raise RuntimeError("Profile update failed")
            return {"status": "updated", "user_id": kwargs.get("user_id")}

    elif service == "order_service":
        if operation == "create_order":
            time.sleep(random.uniform(0.03, 0.08))
            if random.random() < 0.06:  # 6% error rate
                raise ValueError("Invalid order data")
            return {
                "status": "created",
                "order_id": f"order_{random.randint(1000, 9999)}",
            }

        elif operation == "get_order_history":
            time.sleep(random.uniform(0.04, 0.10))
            if random.random() < 0.05:  # 5% error rate
                raise ConnectionError("Order database connection failed")
            return {"status": "success", "orders": [f"order_{i}" for i in range(3)]}

    elif service == "payment_service":
        if operation == "process_payment":
            time.sleep(random.uniform(0.08, 0.20))  # Slower payment processing
            if random.random() < 0.12:  # 12% error rate
                raise TimeoutError("Payment gateway timeout")
            return {
                "status": "processed",
                "payment_id": f"pay_{random.randint(1000, 9999)}",
            }

        elif operation == "verify_payment":
            time.sleep(random.uniform(0.03, 0.07))
            if random.random() < 0.07:  # 7% error rate
                raise ConnectionError("Payment verification service unavailable")
            return {"status": "verified", "amount": kwargs.get("amount", 100)}

    elif service == "notification_service":
        if operation == "send_email":
            time.sleep(random.uniform(0.02, 0.06))
            if random.random() < 0.04:  # 4% error rate
                raise RuntimeError("SMTP server error")
            return {
                "status": "sent",
                "email_id": f"email_{random.randint(1000, 9999)}",
            }

        elif operation == "send_push":
            time.sleep(random.uniform(0.01, 0.04))
            if random.random() < 0.03:  # 3% error rate
                raise ConnectionError("Push notification service unavailable")
            return {
                "status": "sent",
                "push_id": f"push_{random.randint(1000, 9999)}",
            }

    elif service == "analytics_service":
        if operation == "track_event":
            time.sleep(random.uniform(0.005, 0.02))
            if random.random() < 0.02:  # 2% error rate
                raise ValueError("Invalid event format")
            return {
                "status": "tracked",
                "event_id": f"evt_{random.randint(1000, 9999)}",
            }

    # Default service behavior
    time.sleep(random.uniform(0.01, 0.05))
    return {"status": "success", "service": service, "operation": operation}


@CallPyBack(
    observers=[distributed_tracing],
    exception_classes=(Exception,),
    default_return={"status": "workflow_failed", "error": True},
)
def distributed_workflow(workflow_type, user_id, **kwargs):
    """Orchestrate complex workflows across multiple microservices."""
    trace_id = f"workflow_{workflow_type}_{user_id}_{int(time.time())}"
    workflow_results = {}

    try:
        if workflow_type == "user_registration":
            # Step 1: API Gateway routing
            gateway_result = microservice_call(
                "api_gateway",
                "route_request",
                target_service="auth_service",
                trace_id=trace_id,
                span_id=f"span_gateway_{user_id}",
                caller_service="client",
            )
            workflow_results["gateway"] = gateway_result

            # Step 2: Create authentication
            auth_result = microservice_call(
                "auth_service",
                "create_user",
                user_id=user_id,
                email=kwargs.get("email"),
                trace_id=trace_id,
                span_id=f"span_auth_{user_id}",
                parent_span=f"span_gateway_{user_id}",
                caller_service="api_gateway",
            )
            workflow_results["auth"] = auth_result

            # Step 3: Create user profile
            profile_result = microservice_call(
                "user_service",
                "create_profile",
                user_id=user_id,
                profile_data=kwargs.get("profile_data", {}),
                trace_id=trace_id,
                span_id=f"span_profile_{user_id}",
                parent_span=f"span_auth_{user_id}",
                caller_service="auth_service",
            )
            workflow_results["profile"] = profile_result

            # Step 4: Send welcome notification
            notification_result = microservice_call(
                "notification_service",
                "send_email",
                user_id=user_id,
                template="welcome",
                trace_id=trace_id,
                span_id=f"span_notif_{user_id}",
                parent_span=f"span_profile_{user_id}",
                caller_service="user_service",
            )
            workflow_results["notification"] = notification_result

            return {
                "status": "user_registered",
                "workflow_results": workflow_results,
            }

        elif workflow_type == "order_processing":
            # Step 1: Authenticate user
            auth_result = microservice_call(
                "auth_service",
                "validate_token",
                user_id=user_id,
                token=kwargs.get("token", "sample_token"),
                trace_id=trace_id,
                span_id=f"span_auth_{user_id}",
                caller_service="api_gateway",
            )
            workflow_results["auth"] = auth_result

            # Step 2: Get user profile
            profile_result = microservice_call(
                "user_service",
                "get_profile",
                user_id=user_id,
                trace_id=trace_id,
                span_id=f"span_profile_{user_id}",
                parent_span=f"span_auth_{user_id}",
                caller_service="auth_service",
            )
            workflow_results["profile"] = profile_result

            # Step 3: Create order
            order_result = microservice_call(
                "order_service",
                "create_order",
                user_id=user_id,
                items=kwargs.get("items", []),
                trace_id=trace_id,
                span_id=f"span_order_{user_id}",
                parent_span=f"span_profile_{user_id}",
                caller_service="user_service",
            )
            workflow_results["order"] = order_result

            # Step 4: Process payment
            payment_result = microservice_call(
                "payment_service",
                "process_payment",
                user_id=user_id,
                amount=kwargs.get("amount", 100),
                order_id=(
                    order_result.get("order_id")
                    if isinstance(order_result, dict)
                    else "unknown"
                ),
                trace_id=trace_id,
                span_id=f"span_payment_{user_id}",
                parent_span=f"span_order_{user_id}",
                caller_service="order_service",
            )
            workflow_results["payment"] = payment_result

            # Step 5: Send confirmation
            confirmation_result = microservice_call(
                "notification_service",
                "send_email",
                user_id=user_id,
                template="order_confirmation",
                trace_id=trace_id,
                span_id=f"span_confirm_{user_id}",
                parent_span=f"span_payment_{user_id}",
                caller_service="payment_service",
            )
            workflow_results["confirmation"] = confirmation_result

            # Step 6: Track analytics
            analytics_result = microservice_call(
                "analytics_service",
                "track_event",
                user_id=user_id,
                event_type="order_completed",
                trace_id=trace_id,
                span_id=f"span_analytics_{user_id}",
                parent_span=f"span_confirm_{user_id}",
                caller_service="notification_service",
            )
            workflow_results["analytics"] = analytics_result

            return {
                "status": "order_completed",
                "workflow_results": workflow_results,
            }

    except Exception as e:
        print(f"Workflow {workflow_type} failed: {e}")
        return {
            "status": "workflow_failed",
            "error": str(e),
            "partial_results": workflow_results,
        }


if __name__ == "__main__":
    # Simulate distributed system load
    print("Simulating distributed microservices architecture...")

    # Individual service tests
    print("1. Testing individual microservices...")
    individual_service_tests = [
        ("api_gateway", "route_request", {"target_service": "user_service"}),
        ("auth_service", "validate_token", {"user_id": "user123", "token": "abc123"}),
        ("user_service", "get_profile", {"user_id": "user123"}),
        ("order_service", "create_order", {"user_id": "user123", "items": ["item1"]}),
        ("payment_service", "process_payment", {"amount": 99.99}),
        ("notification_service", "send_email", {"user_id": "user123"}),
        ("analytics_service", "track_event", {"event": "page_view"}),
    ]

    # Run individual tests multiple times for statistics
    for service, operation, kwargs in individual_service_tests * 5:
        microservice_call(
            service,
            operation,
            caller_service="test_client",
            trace_id=f"test_{service}_{operation}_{time.time()}",
            **kwargs,
        )

    # Concurrent workflow simulation
    print("2. Testing distributed workflows...")

    workflow_configs = [
        (
            "user_registration",
            "user001",
            {"email": "user001@example.com", "profile_data": {"name": "User 1"}},
        ),
        (
            "order_processing",
            "user002",
            {"items": ["item1", "item2"], "amount": 149.99, "token": "token123"},
        ),
        (
            "user_registration",
            "user003",
            {"email": "user003@example.com", "profile_data": {"name": "User 3"}},
        ),
        (
            "order_processing",
            "user001",
            {"items": ["item3"], "amount": 49.99, "token": "token456"},
        ),
        (
            "order_processing",
            "user004",
            {"items": ["item1", "item4"], "amount": 199.99, "token": "token789"},
        ),
        (
            "user_registration",
            "user005",
            {"email": "user005@example.com", "profile_data": {"name": "User 5"}},
        ),
    ]

    # Execute workflows concurrently
    workflow_results = []

    with ThreadPoolExecutor(
        max_workers=4, thread_name_prefix="WorkflowWorker"
    ) as executor:
        futures = []

        for workflow_type, user_id, kwargs in workflow_configs:
            future = executor.submit(
                distributed_workflow, workflow_type, user_id, **kwargs
            )
            futures.append((future, workflow_type, user_id))

        for future, workflow_type, user_id in futures:
            try:
                result = future.result(timeout=30)
                workflow_results.append((workflow_type, user_id, result))
                print(
                    f"  Workflow {workflow_type} for {user_id}: {result.get('status', 'unknown')}"
                )
            except Exception as e:
                print(f"  Workflow {workflow_type} for {user_id} failed: {e}")

    # Additional load simulation
    print("3. Simulating high-load scenarios...")

    high_load_scenarios = [
        # Authentication burst
        *[
            ("auth_service", "validate_token", {"user_id": f"user_{i%20}"})
            for i in range(30)
        ],
        # User service load
        *[
            ("user_service", "get_profile", {"user_id": f"user_{i%15}"})
            for i in range(25)
        ],
        # Payment processing
        *[
            ("payment_service", "process_payment", {"amount": random.randint(10, 500)})
            for i in range(15)
        ],
        # Analytics tracking
        *[
            ("analytics_service", "track_event", {"event": "user_action"})
            for i in range(40)
        ],
    ]

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="LoadTest") as executor:
        load_futures = []

        for service, operation, kwargs in high_load_scenarios:
            future = executor.submit(
                microservice_call,
                service,
                operation,
                caller_service="load_test",
                trace_id=f"load_{service}_{time.time()}",
                **kwargs,
            )
            load_futures.append(future)

        # Collect results
        for future in as_completed(load_futures, timeout=20):
            try:
                result = future.result()
            except Exception:
                pass  # Errors are tracked by observers

    # Generate comprehensive distributed systems report
    print("\n" + "=" * 70)
    print("DISTRIBUTED SYSTEMS MONITORING REPORT")
    print("=" * 70)

    mesh_metrics = service_mesh.get_service_mesh_metrics()
    trace_analysis = distributed_tracing.get_trace_analysis()

    print("Service Mesh Overview:")
    print(f"  Total service calls: {mesh_metrics['total_calls']}")
    print(f"  Services monitored: {len(mesh_metrics['services'])}")
    print(f"  Communication patterns: {len(mesh_metrics['communication_patterns'])}")

    print("\nService Health Status:")
    for service, metrics in mesh_metrics["services"].items():
        health_emoji = "✅" if metrics["health_status"] == "healthy" else "⚠️"
        print(f"  {health_emoji} {service}:")
        print(f"    Requests: {metrics['total_requests']}")
        print(f"    Success rate: {metrics['success_rate']:.1f}%")
        print(f"    Error rate: {metrics['error_rate']:.1f}%")
        print(f"    Avg latency: {metrics['avg_latency_ms']:.1f}ms")
        print(f"    P95 latency: {metrics['p95_latency_ms']:.1f}ms")

    print("\nService Dependencies:")
    for service, dependencies in mesh_metrics["topology"].items():
        if dependencies:
            print(f"  {service} → {', '.join(dependencies)}")

    print("\nCommunication Patterns:")
    sorted_patterns = sorted(
        mesh_metrics["communication_patterns"].items(), key=lambda x: x[1], reverse=True
    )
    for pattern, count in sorted_patterns[:10]:  # Top 10
        print(f"  {pattern}: {count} calls")

    print("\nDistributed Tracing Summary:")
    print(f"  Total traces: {trace_analysis['total_traces']}")
    print(f"  Completed spans: {trace_analysis['completed_spans']}")
    print(f"  Active spans: {trace_analysis['active_spans']}")

    if trace_analysis["trace_summaries"]:
        successful_traces = sum(
            1 for t in trace_analysis["trace_summaries"] if t["success"]
        )
        total_traces = len(trace_analysis["trace_summaries"])
        avg_duration = (
            sum(t["total_duration"] for t in trace_analysis["trace_summaries"])
            / total_traces
        )
        avg_services = (
            sum(t["services_involved"] for t in trace_analysis["trace_summaries"])
            / total_traces
        )

        print(f"  Trace success rate: {(successful_traces/total_traces)*100:.1f}%")
        print(f"  Average trace duration: {avg_duration*1000:.0f}ms")
        print(f"  Average services per trace: {avg_services:.1f}")

    # Workflow analysis
    successful_workflows = sum(
        1
        for _, _, result in workflow_results
        if isinstance(result, dict)
        and result.get("status") in ["user_registered", "order_completed"]
    )

    print("\nWorkflow Analysis:")
    print(f"  Total workflows executed: {len(workflow_results)}")
    print(f"  Successful workflows: {successful_workflows}")
    print(
        f"  Workflow success rate: {(successful_workflows/max(len(workflow_results),1))*100:.1f}%"
    )

    # System insights
    print("\nSystem Insights:")

    # Find bottleneck service
    if mesh_metrics["services"]:
        slowest_service = max(
            mesh_metrics["services"].items(), key=lambda x: x[1]["p95_latency_ms"]
        )
        print(
            f"  Performance bottleneck: {slowest_service[0]} "
            f"(P95: {slowest_service[1]['p95_latency_ms']:.0f}ms)"
        )

        # Find most unreliable service
        least_reliable = max(
            mesh_metrics["services"].items(), key=lambda x: x[1]["error_rate"]
        )
        print(
            f"  Least reliable service: {least_reliable[0]} "
            f"(error rate: {least_reliable[1]['error_rate']:.1f}%)"
        )

        # Service mesh health score
        avg_success_rate = sum(
            s["success_rate"] for s in mesh_metrics["services"].values()
        ) / len(mesh_metrics["services"])
        avg_latency = sum(
            s["avg_latency_ms"] for s in mesh_metrics["services"].values()
        ) / len(mesh_metrics["services"])

        health_score = min(100, avg_success_rate * (100 / max(avg_latency, 1)))
        print(f"  Overall mesh health score: {health_score:.1f}/100")

    # Recommendations
    print("\nRecommendations:")
    for service, metrics in mesh_metrics["services"].items():
        if metrics["error_rate"] > 15:
            print(
                f"  🔧 {service}: High error rate - investigate error patterns and add circuit breakers"
            )
        if metrics["p95_latency_ms"] > 150:
            print(
                f"  ⚡ {service}: High latency - consider caching, optimization, or horizontal scaling"
            )
        if metrics["total_requests"] < 5:
            print(f"  📊 {service}: Low traffic - consider service consolidation")
