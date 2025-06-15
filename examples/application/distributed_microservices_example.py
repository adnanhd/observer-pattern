#!/usr/bin/env python3
"""
Distributed Microservices - Application Example
Demonstrates inter-service communication using request-response patterns.
"""

import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from callpyback import ExecutionMode, emit_event, on_event, plugin_session


@dataclass
class ServiceRequest:
    request_id: str
    service_name: str
    method: str
    payload: Dict[str, Any]
    timeout: float = 10.0


@dataclass
class ServiceResponse:
    request_id: str
    service_name: str
    status: str  # 'success', 'error', 'timeout'
    data: Any = None
    error: Optional[str] = None
    processing_time: float = 0.0


# Microservice event handlers
@on_event("service.*.request")
def handle_service_request(message):
    """Log all service requests"""
    service_name = message.topic.split(".")[1]
    request_id = message.payload.get("request_id", "unknown")
    method = message.payload.get("method", "unknown")
    print(f"📥 {service_name} service: {method} request {request_id}")


@on_event("service.*.response")
def handle_service_response(message):
    """Log all service responses"""
    service_name = message.topic.split(".")[1]
    response_data = message.payload
    status = response_data.get("status", "unknown")
    processing_time = response_data.get("processing_time", 0)
    print(f"📤 {service_name} service: {status} response in {processing_time:.3f}s")


@on_event("microservice.health.*")
def handle_health_check(message):
    """Monitor service health"""
    service_name = message.topic.split(".")[-1]
    health_data = message.payload
    status = health_data.get("status", "unknown")
    print(f"💚 Health check {service_name}: {status}")


class UserService:
    """User management microservice"""

    def __init__(self, service_id: str):
        self.service_id = service_id
        self.users_db = {
            "user_001": {
                "name": "Alice Johnson",
                "email": "alice@example.com",
                "role": "admin",
            },
            "user_002": {
                "name": "Bob Smith",
                "email": "bob@example.com",
                "role": "user",
            },
            "user_003": {
                "name": "Carol Davis",
                "email": "carol@example.com",
                "role": "user",
            },
            "user_004": {
                "name": "David Wilson",
                "email": "david@example.com",
                "role": "manager",
            },
        }
        self.request_count = 0

    def handle_request(self, request: ServiceRequest) -> ServiceResponse:
        """Handle user service requests"""
        start_time = time.time()
        self.request_count += 1

        emit_event(
            "service.user.request",
            {
                "request_id": request.request_id,
                "method": request.method,
                "service_id": self.service_id,
            },
        )

        try:
            # Simulate processing time
            time.sleep(random.uniform(0.05, 0.2))

            if request.method == "get_user":
                user_id = request.payload.get("user_id")
                user_data = self.users_db.get(user_id)

                if user_data:
                    response = ServiceResponse(
                        request.request_id,
                        "user",
                        "success",
                        data=user_data,
                        processing_time=time.time() - start_time,
                    )
                else:
                    response = ServiceResponse(
                        request.request_id,
                        "user",
                        "error",
                        error="User not found",
                        processing_time=time.time() - start_time,
                    )

            elif request.method == "list_users":
                role_filter = request.payload.get("role")
                if role_filter:
                    filtered_users = {
                        uid: user
                        for uid, user in self.users_db.items()
                        if user["role"] == role_filter
                    }
                else:
                    filtered_users = self.users_db

                response = ServiceResponse(
                    request.request_id,
                    "user",
                    "success",
                    data={"users": filtered_users, "count": len(filtered_users)},
                    processing_time=time.time() - start_time,
                )

            elif request.method == "validate_user":
                user_id = request.payload.get("user_id")
                is_valid = user_id in self.users_db

                response = ServiceResponse(
                    request.request_id,
                    "user",
                    "success",
                    data={"valid": is_valid, "user_id": user_id},
                    processing_time=time.time() - start_time,
                )

            else:
                response = ServiceResponse(
                    request.request_id,
                    "user",
                    "error",
                    error=f"Unknown method: {request.method}",
                    processing_time=time.time() - start_time,
                )

            emit_event(
                "service.user.response",
                {
                    "request_id": request.request_id,
                    "status": response.status,
                    "processing_time": response.processing_time,
                },
            )

            return response

        except Exception as e:
            response = ServiceResponse(
                request.request_id,
                "user",
                "error",
                error=str(e),
                processing_time=time.time() - start_time,
            )

            emit_event(
                "service.user.response",
                {
                    "request_id": request.request_id,
                    "status": "error",
                    "error": str(e),
                    "processing_time": response.processing_time,
                },
            )

            return response


class OrderService:
    """Order management microservice"""

    def __init__(self, service_id: str):
        self.service_id = service_id
        self.orders_db = {}
        self.order_counter = 1000
        self.request_count = 0

    def handle_request(self, request: ServiceRequest) -> ServiceResponse:
        """Handle order service requests"""
        start_time = time.time()
        self.request_count += 1

        emit_event(
            "service.order.request",
            {
                "request_id": request.request_id,
                "method": request.method,
                "service_id": self.service_id,
            },
        )

        try:
            # Simulate processing time
            time.sleep(random.uniform(0.1, 0.3))

            if request.method == "create_order":
                order_id = f"ORD_{self.order_counter}"
                self.order_counter += 1

                order_data = {
                    "order_id": order_id,
                    "user_id": request.payload.get("user_id"),
                    "items": request.payload.get("items", []),
                    "total": request.payload.get("total", 0.0),
                    "status": "pending",
                    "created_at": time.time(),
                }

                self.orders_db[order_id] = order_data

                response = ServiceResponse(
                    request.request_id,
                    "order",
                    "success",
                    data=order_data,
                    processing_time=time.time() - start_time,
                )

            elif request.method == "get_order":
                order_id = request.payload.get("order_id")
                order_data = self.orders_db.get(order_id)

                if order_data:
                    response = ServiceResponse(
                        request.request_id,
                        "order",
                        "success",
                        data=order_data,
                        processing_time=time.time() - start_time,
                    )
                else:
                    response = ServiceResponse(
                        request.request_id,
                        "order",
                        "error",
                        error="Order not found",
                        processing_time=time.time() - start_time,
                    )

            elif request.method == "list_user_orders":
                user_id = request.payload.get("user_id")
                user_orders = {
                    oid: order
                    for oid, order in self.orders_db.items()
                    if order["user_id"] == user_id
                }

                response = ServiceResponse(
                    request.request_id,
                    "order",
                    "success",
                    data={"orders": user_orders, "count": len(user_orders)},
                    processing_time=time.time() - start_time,
                )

            else:
                response = ServiceResponse(
                    request.request_id,
                    "order",
                    "error",
                    error=f"Unknown method: {request.method}",
                    processing_time=time.time() - start_time,
                )

            emit_event(
                "service.order.response",
                {
                    "request_id": request.request_id,
                    "status": response.status,
                    "processing_time": response.processing_time,
                },
            )

            return response

        except Exception as e:
            response = ServiceResponse(
                request.request_id,
                "order",
                "error",
                error=str(e),
                processing_time=time.time() - start_time,
            )

            emit_event(
                "service.order.response",
                {
                    "request_id": request.request_id,
                    "status": "error",
                    "error": str(e),
                    "processing_time": response.processing_time,
                },
            )

            return response


class PaymentService:
    """Payment processing microservice"""

    def __init__(self, service_id: str):
        self.service_id = service_id
        self.payments_db = {}
        self.payment_counter = 5000
        self.request_count = 0

    def handle_request(self, request: ServiceRequest) -> ServiceResponse:
        """Handle payment service requests"""
        start_time = time.time()
        self.request_count += 1

        emit_event(
            "service.payment.request",
            {
                "request_id": request.request_id,
                "method": request.method,
                "service_id": self.service_id,
            },
        )

        try:
            # Simulate payment processing time (longer than other services)
            time.sleep(random.uniform(0.2, 0.5))

            if request.method == "process_payment":
                payment_id = f"PAY_{self.payment_counter}"
                self.payment_counter += 1

                # Simulate payment success/failure (90% success rate)
                success = random.random() > 0.1

                payment_data = {
                    "payment_id": payment_id,
                    "order_id": request.payload.get("order_id"),
                    "user_id": request.payload.get("user_id"),
                    "amount": request.payload.get("amount", 0.0),
                    "status": "completed" if success else "failed",
                    "processed_at": time.time(),
                }

                self.payments_db[payment_id] = payment_data

                response = ServiceResponse(
                    request.request_id,
                    "payment",
                    "success" if success else "error",
                    data=payment_data if success else None,
                    error=None if success else "Payment processing failed",
                    processing_time=time.time() - start_time,
                )

            elif request.method == "get_payment":
                payment_id = request.payload.get("payment_id")
                payment_data = self.payments_db.get(payment_id)

                response = ServiceResponse(
                    request.request_id,
                    "payment",
                    "success" if payment_data else "error",
                    data=payment_data,
                    error=None if payment_data else "Payment not found",
                    processing_time=time.time() - start_time,
                )

            else:
                response = ServiceResponse(
                    request.request_id,
                    "payment",
                    "error",
                    error=f"Unknown method: {request.method}",
                    processing_time=time.time() - start_time,
                )

            emit_event(
                "service.payment.response",
                {
                    "request_id": request.request_id,
                    "status": response.status,
                    "processing_time": response.processing_time,
                },
            )

            return response

        except Exception as e:
            response = ServiceResponse(
                request.request_id,
                "payment",
                "error",
                error=str(e),
                processing_time=time.time() - start_time,
            )

            emit_event(
                "service.payment.response",
                {
                    "request_id": request.request_id,
                    "status": "error",
                    "error": str(e),
                    "processing_time": response.processing_time,
                },
            )

            return response


def simulate_business_workflow(workflow_id: str, services: Dict) -> Dict:
    """Simulate complex business workflow involving multiple services"""

    workflow_start = time.time()
    results = {"workflow_id": workflow_id, "steps": []}

    try:
        # Step 1: Validate user
        user_id = f"user_{random.randint(1, 4):03d}"
        user_request = ServiceRequest(
            f"{workflow_id}_user_check", "user", "validate_user", {"user_id": user_id}
        )

        user_response = services["user"].handle_request(user_request)
        results["steps"].append({"step": "user_validation", "response": user_response})

        if user_response.status != "success" or not user_response.data.get("valid"):
            raise ValueError(f"Invalid user: {user_id}")

        # Step 2: Create order
        order_request = ServiceRequest(
            f"{workflow_id}_create_order",
            "order",
            "create_order",
            {
                "user_id": user_id,
                "items": [
                    {
                        "product_id": "PROD_A",
                        "quantity": random.randint(1, 3),
                        "price": 29.99,
                    },
                    {
                        "product_id": "PROD_B",
                        "quantity": random.randint(1, 2),
                        "price": 49.99,
                    },
                ],
                "total": round(random.uniform(50.0, 200.0), 2),
            },
        )

        order_response = services["order"].handle_request(order_request)
        results["steps"].append({"step": "order_creation", "response": order_response})

        if order_response.status != "success":
            raise ValueError("Order creation failed")

        order_data = order_response.data

        # Step 3: Process payment
        payment_request = ServiceRequest(
            f"{workflow_id}_payment",
            "payment",
            "process_payment",
            {
                "order_id": order_data["order_id"],
                "user_id": user_id,
                "amount": order_data["total"],
            },
        )

        payment_response = services["payment"].handle_request(payment_request)
        results["steps"].append(
            {"step": "payment_processing", "response": payment_response}
        )

        # Workflow completion
        workflow_time = time.time() - workflow_start
        results["status"] = (
            "completed" if payment_response.status == "success" else "failed"
        )
        results["total_time"] = workflow_time
        results["user_id"] = user_id
        results["order_id"] = order_data["order_id"]

        if payment_response.status == "success":
            results["payment_id"] = payment_response.data["payment_id"]

        emit_event(
            "workflow.completed",
            {
                "workflow_id": workflow_id,
                "status": results["status"],
                "total_time": workflow_time,
                "steps_completed": len(results["steps"]),
            },
        )

        return results

    except Exception as e:
        workflow_time = time.time() - workflow_start
        results["status"] = "failed"
        results["error"] = str(e)
        results["total_time"] = workflow_time

        emit_event(
            "workflow.failed",
            {"workflow_id": workflow_id, "error": str(e), "total_time": workflow_time},
        )

        return results


def health_check_service(service_name: str, service_instance) -> Dict:
    """Perform health check on a service"""
    start_time = time.time()

    try:
        # Check service responsiveness
        health_data = {
            "service_name": service_name,
            "status": "healthy",
            "request_count": getattr(service_instance, "request_count", 0),
            "uptime": time.time() - start_time,
            "memory_usage": random.randint(50, 200),  # Simulated MB
            "cpu_usage": random.uniform(5.0, 25.0),  # Simulated %
        }

        # Simulate occasional service issues
        if random.random() < 0.05:  # 5% chance of issues
            health_data["status"] = "degraded"
            health_data["issues"] = ["High response time", "Memory pressure"]

        emit_event(f"microservice.health.{service_name}", health_data)
        return health_data

    except Exception as e:
        error_data = {
            "service_name": service_name,
            "status": "unhealthy",
            "error": str(e),
        }
        emit_event(f"microservice.health.{service_name}", error_data)
        return error_data


def main():
    """Demo distributed microservices communication"""
    print("🌐 Distributed Microservices Communication")
    print("=" * 50)

    # Create service instances
    user_service = UserService("UserSvc-001")
    order_service = OrderService("OrderSvc-001")
    payment_service = PaymentService("PaymentSvc-001")

    services = {
        "user": user_service,
        "order": order_service,
        "payment": payment_service,
    }

    with plugin_session() as manager:
        # Configure for I/O intensive microservice communication
        manager.configure().max_threads(6).execution_mode(ExecutionMode.THREAD).apply()

        print("🚀 Running distributed business workflows...")

        # Generate workflow IDs
        workflow_ids = [
            f"WF_{int(time.time() * 1000) % 10000}_{i:02d}" for i in range(8)
        ]

        # Run business workflows in parallel
        start_time = time.time()
        workflow_results = manager.map_parallel(
            lambda wf_id: simulate_business_workflow(wf_id, services), workflow_ids
        )
        total_time = time.time() - start_time

        # Analyze workflow results
        successful_workflows = [
            w for w in workflow_results if w.get("status") == "completed"
        ]
        failed_workflows = [w for w in workflow_results if w.get("status") == "failed"]

        print(f"\n📊 Workflow Results:")
        print(f"   ✅ Successful workflows: {len(successful_workflows)}")
        print(f"   ❌ Failed workflows: {len(failed_workflows)}")
        print(f"   ⏱️ Total execution time: {total_time:.2f}s")

        if successful_workflows:
            avg_workflow_time = sum(
                w.get("total_time", 0) for w in successful_workflows
            ) / len(successful_workflows)
            print(f"   📈 Average workflow time: {avg_workflow_time:.2f}s")

        # Run health checks in parallel
        print(f"\n💚 Running service health checks...")
        health_results = manager.parallel(
            lambda: health_check_service("user", user_service),
            lambda: health_check_service("order", order_service),
            lambda: health_check_service("payment", payment_service),
        )

        # Show service statistics
        print(f"\n📋 Service Statistics:")
        for service_name, service_instance in services.items():
            request_count = getattr(service_instance, "request_count", 0)
            print(
                f"   {service_name.capitalize()} Service: {request_count} requests processed"
            )

        # Show health check results
        print(f"\n💚 Health Check Results:")
        for health in health_results:
            service_name = health.get("service_name", "unknown")
            status = health.get("status", "unknown")
            memory = health.get("memory_usage", 0)
            cpu = health.get("cpu_usage", 0)
            print(f"   {service_name}: {status} (Memory: {memory}MB, CPU: {cpu:.1f}%)")

        # Show system performance
        metrics = manager.get_metrics()
        print(f"\n📈 System Performance:")
        print(f"   Total requests: {metrics['tasks_completed']}")
        print(f"   Events generated: {metrics['events_published']}")
        print(f"   System health: {manager.health_check()}")

        print(f"\n🎯 Architecture demonstrates:")
        print(f"   ✅ Request-response communication patterns")
        print(f"   ✅ Service isolation and independence")
        print(f"   ✅ Complex multi-step business workflows")
        print(f"   ✅ Service health monitoring")
        print(f"   ✅ Parallel processing across services")


if __name__ == "__main__":
    main()
