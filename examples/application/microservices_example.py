#!/usr/bin/env python3
"""
Uses existing CallPyBack plugins: EventBus, TopicRegistry, ThreadExecutor
"""

import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict

from callpyback import CallPyBack, on_call, on_failure, on_success
from callpyback.observers.base import BaseObserver
from callpyback.plugins.core.message_queue import EventBus
from callpyback.plugins.core.topic_registry import TopicRegistry
from callpyback.plugins.executors.thread_executor import ThreadExecutor


class ServiceStatus(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


@dataclass
class ServiceCall:
    service_name: str
    operation: str
    data: Dict[str, Any]
    caller_service: str = "unknown"
    trace_id: str = ""
    timeout: float = 5.0


class MicroserviceObserver(BaseObserver):
    """Microservice calls monitoring"""

    def __init__(self):
        super().__init__(priority=90, name="Microservice")
        self.service_metrics = {}
        self.total_calls = 0
        self.failures = 0
        self.avg_response_time = 0.0

    def update(self, context):
        if context.state.name == "COMPLETED":
            self.total_calls += 1

            if context.result and context.result.value:
                result = context.result.value
                service = result.get("service_name", "unknown")

                if service not in self.service_metrics:
                    self.service_metrics[service] = {
                        "calls": 0,
                        "errors": 0,
                        "total_time": 0.0,
                    }

                self.service_metrics[service]["calls"] += 1

                response_time = result.get("response_time", 0)
                self.service_metrics[service]["total_time"] += response_time

                # Update global average
                total_time = sum(m["total_time"] for m in self.service_metrics.values())
                self.avg_response_time = (
                    total_time / self.total_calls if self.total_calls > 0 else 0
                )

        elif context.state.name == "FAILED":
            self.failures += 1


# Global instances
microservice_observer = MicroserviceObserver()
event_bus = EventBus()
topic_registry = TopicRegistry()
thread_executor = ThreadExecutor(max_workers=8)


# Mock service implementations
class MockServices:
    """Mock microservice implementations"""

    @staticmethod
    def user_service(operation: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """User management service"""
        time.sleep(random.uniform(0.02, 0.1))  # Simulate processing

        if operation == "get_user":
            user_id = data.get("user_id", "unknown")
            return {
                "user_id": user_id,
                "name": f"User {user_id}",
                "email": f"user{user_id}@example.com",
                "status": "active",
            }
        elif operation == "create_user":
            return {
                "user_id": f"user_{random.randint(1000, 9999)}",
                "status": "created",
                "created_at": time.time(),
            }
        elif operation == "update_user":
            return {"status": "updated", "updated_at": time.time()}

        return {"error": f"Unknown operation: {operation}"}

    @staticmethod
    def order_service(operation: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Order management service"""
        time.sleep(random.uniform(0.05, 0.15))

        if operation == "create_order":
            items = data.get("items", [])
            if not items:
                raise ValueError("Order must have items")

            return {
                "order_id": f"order_{random.randint(10000, 99999)}",
                "items": items,
                "total": random.uniform(10.0, 500.0),
                "status": "created",
            }
        elif operation == "get_order":
            order_id = data.get("order_id", "unknown")
            return {
                "order_id": order_id,
                "status": random.choice(["pending", "processing", "completed"]),
            }
        elif operation == "cancel_order":
            return {"status": "cancelled", "cancelled_at": time.time()}

        return {"error": f"Unknown operation: {operation}"}

    @staticmethod
    def payment_service(operation: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Payment processing service"""
        time.sleep(random.uniform(0.1, 0.3))  # Payment takes longer

        if operation == "process_payment":
            amount = data.get("amount", 0)
            if amount <= 0:
                raise ValueError("Invalid payment amount")

            # Simulate payment processing failures
            if random.random() < 0.1:  # 10% failure rate
                raise RuntimeError("Payment gateway error")

            return {
                "payment_id": f"pay_{random.randint(100000, 999999)}",
                "amount": amount,
                "status": "completed",
                "transaction_id": f"txn_{random.randint(1000000, 9999999)}",
            }
        elif operation == "refund_payment":
            return {
                "refund_id": f"ref_{random.randint(100000, 999999)}",
                "status": "processed",
            }

        return {"error": f"Unknown operation: {operation}"}

    @staticmethod
    def notification_service(operation: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Notification service"""
        time.sleep(random.uniform(0.01, 0.05))

        if operation == "send_notification":
            notification_type = data.get("type", "email")
            return {
                "notification_id": f"notif_{random.randint(10000, 99999)}",
                "type": notification_type,
                "status": "sent",
                "sent_at": time.time(),
            }

        return {"error": f"Unknown operation: {operation}"}


@CallPyBack(
    observers=[
        microservice_observer,
        on_call(
            lambda context: print(
                f"📞 {context.arguments['service_call'].service_name}.{context.arguments['service_call'].operation}"
            )
        ),
        on_success(
            lambda result: event_bus.publish("service.call.completed", result.value)
        ),
        on_failure(
            lambda result: event_bus.publish(
                "service.call.failed", {"error": str(result.exception)}
            )
        ),
    ]
)
def call_microservice(service_call: ServiceCall) -> Dict[str, Any]:
    """Call a microservice with monitoring"""

    start_time = time.time()

    try:
        # Get service implementation
        services = {
            "user_service": MockServices.user_service,
            "order_service": MockServices.order_service,
            "payment_service": MockServices.payment_service,
            "notification_service": MockServices.notification_service,
        }

        service_func = services.get(service_call.service_name)
        if not service_func:
            raise ValueError(f"Unknown service: {service_call.service_name}")

        # Execute service call
        result = service_func(service_call.operation, service_call.data)
        response_time = time.time() - start_time

        return {
            "service_name": service_call.service_name,
            "operation": service_call.operation,
            "response_time": response_time,
            "trace_id": service_call.trace_id,
            "caller_service": service_call.caller_service,
            "result": result,
            "status": "success",
        }

    except Exception as e:
        response_time = time.time() - start_time
        return {
            "service_name": service_call.service_name,
            "operation": service_call.operation,
            "response_time": response_time,
            "trace_id": service_call.trace_id,
            "caller_service": service_call.caller_service,
            "error": str(e),
            "status": "failed",
        }


class SimpleMicroservicesOrchestrator:
    """Simplified microservices orchestrator"""

    def __init__(self):
        self.event_bus = event_bus
        self.topic_registry = topic_registry
        self.executor = thread_executor
        self.observer = microservice_observer

        # Start services
        self.executor.start()

        # Register topics
        self._register_topics()

        # Setup event handlers
        self.event_bus.subscribe("service.call.completed", self._on_service_completed)
        self.event_bus.subscribe("service.call.failed", self._on_service_failed)
        self.event_bus.subscribe("workflow.completed", self._on_workflow_completed)

    def _register_topics(self):
        """Register service communication topics"""
        topics = [
            ("service.call.completed", "Service call completed successfully"),
            ("service.call.failed", "Service call failed"),
            ("workflow.completed", "Multi-service workflow completed"),
            ("user.events", "User-related events"),
            ("order.events", "Order-related events"),
            ("payment.events", "Payment-related events"),
        ]

        for topic_name, description in topics:
            self.topic_registry.register_topic(topic_name, description)

    def _on_service_completed(self, message):
        """Handle service call completion"""
        payload = message.payload
        service = payload.get("service_name", "unknown")
        operation = payload.get("operation", "unknown")
        response_time = payload.get("response_time", 0)
        print(f"✅ {service}.{operation}: {response_time:.3f}s")

    def _on_service_failed(self, message):
        """Handle service call failure"""
        error = message.payload.get("error", "Unknown error")
        print(f"❌ Service call failed: {error}")

    def _on_workflow_completed(self, message):
        """Handle workflow completion"""
        payload = message.payload
        workflow_type = payload.get("workflow_type", "unknown")
        print(f"🎯 Workflow completed: {workflow_type}")

    def create_service_call(
        self,
        service_name: str,
        operation: str,
        data: Dict[str, Any],
        caller: str = "orchestrator",
        trace_id: str = None,
    ) -> ServiceCall:
        """Create a service call"""
        if not trace_id:
            trace_id = f"trace_{int(time.time() * 1000) % 100000}"

        return ServiceCall(
            service_name=service_name,
            operation=operation,
            data=data,
            caller_service=caller,
            trace_id=trace_id,
        )

    def execute_workflow(
        self, workflow_type: str, user_id: str, **kwargs
    ) -> Dict[str, Any]:
        """Execute a multi-service workflow"""

        trace_id = f"workflow_{workflow_type}_{user_id}_{int(time.time())}"
        print(f"🔄 Executing {workflow_type} workflow for user {user_id}")

        try:
            if workflow_type == "user_registration":
                # Step 1: Create user
                user_call = self.create_service_call(
                    "user_service",
                    "create_user",
                    {"email": kwargs.get("email"), "name": kwargs.get("name")},
                    trace_id=trace_id,
                )
                user_result = call_microservice(user_call)

                if user_result["status"] != "success":
                    raise ValueError(
                        f"User creation failed: {user_result.get('error')}"
                    )

                # Step 2: Send welcome notification
                notif_call = self.create_service_call(
                    "notification_service",
                    "send_notification",
                    {"user_id": user_result["result"]["user_id"], "type": "welcome"},
                    trace_id=trace_id,
                )
                notif_result = call_microservice(notif_call)

                return {
                    "workflow_type": workflow_type,
                    "user_id": user_result["result"]["user_id"],
                    "steps_completed": ["user_creation", "welcome_notification"],
                    "trace_id": trace_id,
                    "status": "completed",
                }

            elif workflow_type == "order_processing":
                # Step 1: Create order
                order_call = self.create_service_call(
                    "order_service",
                    "create_order",
                    {"user_id": user_id, "items": kwargs.get("items", [])},
                    trace_id=trace_id,
                )
                order_result = call_microservice(order_call)

                if order_result["status"] != "success":
                    raise ValueError(
                        f"Order creation failed: {order_result.get('error')}"
                    )

                # Step 2: Process payment
                payment_call = self.create_service_call(
                    "payment_service",
                    "process_payment",
                    {
                        "order_id": order_result["result"]["order_id"],
                        "amount": kwargs.get("amount", 100.0),
                    },
                    trace_id=trace_id,
                )
                payment_result = call_microservice(payment_call)

                if payment_result["status"] != "success":
                    # Cancel order if payment fails
                    cancel_call = self.create_service_call(
                        "order_service",
                        "cancel_order",
                        {"order_id": order_result["result"]["order_id"]},
                        trace_id=trace_id,
                    )
                    call_microservice(cancel_call)
                    raise ValueError(f"Payment failed: {payment_result.get('error')}")

                # Step 3: Send confirmation
                confirm_call = self.create_service_call(
                    "notification_service",
                    "send_notification",
                    {
                        "user_id": user_id,
                        "type": "order_confirmation",
                        "order_id": order_result["result"]["order_id"],
                    },
                    trace_id=trace_id,
                )
                call_microservice(confirm_call)

                return {
                    "workflow_type": workflow_type,
                    "user_id": user_id,
                    "order_id": order_result["result"]["order_id"],
                    "payment_id": payment_result["result"]["payment_id"],
                    "steps_completed": [
                        "order_creation",
                        "payment_processing",
                        "confirmation",
                    ],
                    "trace_id": trace_id,
                    "status": "completed",
                }

            else:
                raise ValueError(f"Unknown workflow type: {workflow_type}")

        except Exception as e:
            return {
                "workflow_type": workflow_type,
                "user_id": user_id,
                "trace_id": trace_id,
                "status": "failed",
                "error": str(e),
            }

    def test_service_health(self) -> Dict[str, ServiceStatus]:
        """Test health of all services"""
        print("🏥 Testing service health...")

        health_checks = [
            ("user_service", "get_user", {"user_id": "health_check"}),
            ("order_service", "get_order", {"order_id": "health_check"}),
            ("payment_service", "process_payment", {"amount": 1.0}),
            ("notification_service", "send_notification", {"type": "test"}),
        ]

        service_health = {}

        for service_name, operation, data in health_checks:
            try:
                service_call = self.create_service_call(
                    service_name, operation, data, "health_checker"
                )
                result = call_microservice(service_call)

                if result["status"] == "success":
                    if result["response_time"] < 0.5:
                        service_health[service_name] = ServiceStatus.HEALTHY
                    else:
                        service_health[service_name] = ServiceStatus.DEGRADED
                else:
                    service_health[service_name] = ServiceStatus.DOWN

            except Exception:
                service_health[service_name] = ServiceStatus.DOWN

        return service_health

    def get_service_metrics(self) -> Dict[str, Any]:
        """Get microservices metrics"""
        return {
            "total_calls": self.observer.total_calls,
            "total_failures": self.observer.failures,
            "success_rate": (self.observer.total_calls - self.observer.failures)
            / max(self.observer.total_calls, 1),
            "avg_response_time": self.observer.avg_response_time,
            "service_metrics": self.observer.service_metrics,
            "topic_stats": self.topic_registry.get_stats(),
        }

    def shutdown(self):
        """Clean shutdown"""
        self.executor.stop()


def main():
    """Demo the simplified microservices orchestrator"""
    orchestrator = SimpleMicroservicesOrchestrator()

    try:
        # Test service health
        health_status = orchestrator.test_service_health()
        print(f"\n🏥 Service Health Status:")
        for service, status in health_status.items():
            status_icon = (
                "✅"
                if status == ServiceStatus.HEALTHY
                else "⚠️" if status == ServiceStatus.DEGRADED else "❌"
            )
            print(f"  {status_icon} {service}: {status.value}")

        # Execute individual service calls
        print(f"\n📞 Testing individual service calls...")
        test_calls = [
            ("user_service", "get_user", {"user_id": "test_user"}),
            (
                "order_service",
                "create_order",
                {"user_id": "test_user", "items": ["item1", "item2"]},
            ),
            (
                "notification_service",
                "send_notification",
                {"user_id": "test_user", "type": "test"},
            ),
        ]

        for service, operation, data in test_calls:
            service_call = orchestrator.create_service_call(service, operation, data)
            result = call_microservice(service_call)
            print(
                f"  {service}.{operation}: {'✅' if result['status'] == 'success' else '❌'}"
            )

        # Execute workflows
        print(f"\n🔄 Testing workflows...")

        # User registration workflow
        reg_result = orchestrator.execute_workflow(
            "user_registration",
            "new_user_001",
            email="newuser@example.com",
            name="New User",
        )
        print(
            f"  Registration: {'✅' if reg_result['status'] == 'completed' else '❌'}"
        )

        # Order processing workflow
        order_result = orchestrator.execute_workflow(
            "order_processing", "user_002", items=["product1", "product2"], amount=99.99
        )
        print(
            f"  Order processing: {'✅' if order_result['status'] == 'completed' else '❌'}"
        )

        # Show metrics
        metrics = orchestrator.get_service_metrics()
        print(f"\n📊 Microservices Metrics:")
        print(f"  Total calls: {metrics['total_calls']}")
        print(f"  Success rate: {metrics['success_rate']:.1%}")
        print(f"  Avg response time: {metrics['avg_response_time']:.3f}s")
        print(f"  Services called: {len(metrics['service_metrics'])}")

    finally:
        orchestrator.shutdown()


if __name__ == "__main__":
    main()
