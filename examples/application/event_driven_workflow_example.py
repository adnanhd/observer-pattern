#!/usr/bin/env python3
"""
Event-Driven Workflow Engine - Application Example
Demonstrates complex event patterns, workflows, and orchestration using v3 API.
"""

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from callpyback import (
    ExecutionMode,
    Executor,
    MessageQueue,
    TaskResult,
    TaskStatus,
)


class WorkflowStatus(Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowStep:
    step_id: str
    step_type: str
    name: str
    config: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Any = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class WorkflowInstance:
    workflow_id: str
    workflow_name: str
    steps: Dict[str, WorkflowStep]
    status: WorkflowStatus = WorkflowStatus.CREATED
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class WorkflowEngine:
    """Event-driven workflow execution engine using MessageQueue."""

    def __init__(self, engine_id: str, queue: MessageQueue):
        self.engine_id = engine_id
        self.queue = queue
        self.workflows: Dict[str, WorkflowInstance] = {}
        self.step_processors: Dict[str, Callable] = {}
        self.running_workflows: Dict[str, bool] = {}

        # Register built-in step processors
        self._register_builtin_processors()

        # Setup event handlers
        self._setup_event_handlers()

    def _setup_event_handlers(self):
        """Setup message queue event handlers."""

        @self.queue.on("workflow.*.created")
        def handle_workflow_created(message):
            workflow_type = message.topic.split(".")[1]
            payload = message.payload
            workflow_id = payload.get("workflow_id", "unknown")
            step_count = payload.get("step_count", 0)
            print(
                f"[Workflow] Created: {workflow_type} ({workflow_id}) with {step_count} steps"
            )

        @self.queue.on("workflow.*.started")
        def handle_workflow_started(message):
            workflow_type = message.topic.split(".")[1]
            payload = message.payload
            workflow_id = payload.get("workflow_id", "unknown")
            trigger = payload.get("trigger", "manual")
            print(
                f"[Workflow] Started: {workflow_type} ({workflow_id}) - Trigger: {trigger}"
            )

        @self.queue.on("workflow.step.*.started")
        def handle_step_started(message):
            step_type = message.topic.split(".")[2]
            payload = message.payload
            step_id = payload.get("step_id", "unknown")
            print(f"  [Step] Started: {step_type} ({step_id})")

        @self.queue.on("workflow.step.*.completed")
        def handle_step_completed(message):
            step_type = message.topic.split(".")[2]
            payload = message.payload
            step_id = payload.get("step_id", "unknown")
            duration = payload.get("duration", 0)
            print(f"  [Step] Completed: {step_type} ({step_id}) in {duration:.2f}s")

        @self.queue.on("workflow.*.completed")
        def handle_workflow_completed(message):
            workflow_type = message.topic.split(".")[1]
            payload = message.payload
            workflow_id = payload.get("workflow_id", "unknown")
            total_duration = payload.get("total_duration", 0)
            steps_completed = payload.get("steps_completed", 0)
            print(
                f"[Workflow] Completed: {workflow_type} ({workflow_id}) - {steps_completed} steps in {total_duration:.2f}s"
            )

        @self.queue.on("workflow.step.*.failed")
        def handle_step_failed(message):
            step_type = message.topic.split(".")[2]
            payload = message.payload
            step_id = payload.get("step_id", "unknown")
            error = payload.get("error", "Unknown error")
            retry_count = payload.get("retry_count", 0)
            print(
                f"  [Step] Failed: {step_type} ({step_id}) - {error} (retry {retry_count})"
            )

        @self.queue.on("workflow.*.failed")
        def handle_workflow_failed(message):
            workflow_type = message.topic.split(".")[1]
            payload = message.payload
            workflow_id = payload.get("workflow_id", "unknown")
            failed_step = payload.get("failed_step", "unknown")
            error = payload.get("error", "Unknown error")
            print(
                f"[Workflow] Failed: {workflow_type} ({workflow_id}) at step {failed_step} - {error}"
            )

        @self.queue.on("condition.*.evaluated")
        def handle_condition_evaluation(message):
            condition_type = message.topic.split(".")[1]
            payload = message.payload
            condition_id = payload.get("condition_id", "unknown")
            result = payload.get("result", False)
            expression = payload.get("expression", "unknown")
            print(
                f"  [Condition] {condition_type} ({condition_id}) - {expression} = {result}"
            )

    def _register_builtin_processors(self):
        """Register built-in step processors."""
        self.step_processors["http_request"] = self._process_http_request_step
        self.step_processors["data_validation"] = self._process_data_validation_step
        self.step_processors["transformation"] = self._process_transformation_step
        self.step_processors["notification"] = self._process_notification_step
        self.step_processors["approval"] = self._process_approval_step
        self.step_processors["condition"] = self._process_condition_step
        self.step_processors["delay"] = self._process_delay_step
        self.step_processors["parallel_branch"] = self._process_parallel_branch_step

    def create_workflow(self, workflow_name: str, steps: List[Dict[str, Any]]) -> str:
        """Create a new workflow instance."""
        workflow_id = (
            f"wf_{int(time.time() * 1000) % 100000}_{random.randint(100, 999)}"
        )

        workflow_steps = {}
        for step_config in steps:
            step = WorkflowStep(
                step_id=step_config["step_id"],
                step_type=step_config["step_type"],
                name=step_config["name"],
                config=step_config.get("config", {}),
                dependencies=step_config.get("dependencies", []),
                max_retries=step_config.get("max_retries", 3),
            )
            workflow_steps[step.step_id] = step

        workflow = WorkflowInstance(
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            steps=workflow_steps,
        )

        self.workflows[workflow_id] = workflow

        self.queue.publish(
            f"workflow.{workflow_name}.created",
            {
                "workflow_id": workflow_id,
                "workflow_name": workflow_name,
                "step_count": len(workflow_steps),
                "engine_id": self.engine_id,
            },
        )

        return workflow_id

    def start_workflow(
        self,
        workflow_id: str,
        trigger: str = "manual",
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Start workflow execution."""
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            return False

        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = time.time()
        workflow.context.update(initial_context or {})

        self.running_workflows[workflow_id] = True

        self.queue.publish(
            f"workflow.{workflow.workflow_name}.started",
            {
                "workflow_id": workflow_id,
                "workflow_name": workflow.workflow_name,
                "trigger": trigger,
                "context": workflow.context,
            },
        )

        return True

    def execute_workflow(self, workflow_id: str) -> bool:
        """Execute workflow steps."""
        workflow = self.workflows.get(workflow_id)
        if not workflow or not self.running_workflows.get(workflow_id):
            return False

        try:
            while self.running_workflows.get(workflow_id):
                ready_steps = self._get_ready_steps(workflow)

                if not ready_steps:
                    if self._is_workflow_complete(workflow):
                        self._complete_workflow(workflow)
                        break
                    else:
                        time.sleep(0.1)
                        continue

                for step in ready_steps:
                    self._execute_step(workflow, step)

                time.sleep(0.05)

            return True

        except Exception as e:
            self._fail_workflow(workflow, str(e))
            return False

    def _get_ready_steps(self, workflow: WorkflowInstance) -> List[WorkflowStep]:
        """Get steps that are ready to execute."""
        ready_steps = []

        for step in workflow.steps.values():
            if step.status != StepStatus.PENDING:
                continue

            dependencies_met = True
            for dep_id in step.dependencies:
                dep_step = workflow.steps.get(dep_id)
                if not dep_step or dep_step.status != StepStatus.COMPLETED:
                    dependencies_met = False
                    break

            if dependencies_met:
                ready_steps.append(step)

        return ready_steps

    def _execute_step(self, workflow: WorkflowInstance, step: WorkflowStep):
        """Execute a single workflow step."""
        step.status = StepStatus.RUNNING
        step.started_at = time.time()

        self.queue.publish(
            f"workflow.step.{step.step_type}.started",
            {
                "workflow_id": workflow.workflow_id,
                "step_id": step.step_id,
                "step_type": step.step_type,
                "step_name": step.name,
            },
        )

        try:
            processor = self.step_processors.get(step.step_type)
            if not processor:
                raise ValueError(f"No processor for step type: {step.step_type}")

            result = processor(workflow, step)

            step.status = StepStatus.COMPLETED
            step.completed_at = time.time()
            step.result = result

            duration = step.completed_at - step.started_at

            self.queue.publish(
                f"workflow.step.{step.step_type}.completed",
                {
                    "workflow_id": workflow.workflow_id,
                    "step_id": step.step_id,
                    "step_type": step.step_type,
                    "duration": duration,
                    "result": result,
                },
            )

        except Exception as e:
            self._fail_step(workflow, step, str(e))

    def _fail_step(self, workflow: WorkflowInstance, step: WorkflowStep, error: str):
        """Handle step failure."""
        step.retry_count += 1
        step.error = error

        if step.retry_count <= step.max_retries:
            step.status = StepStatus.PENDING
            step.started_at = None

            self.queue.publish(
                f"workflow.step.{step.step_type}.retrying",
                {
                    "workflow_id": workflow.workflow_id,
                    "step_id": step.step_id,
                    "error": error,
                    "retry_count": step.retry_count,
                    "max_retries": step.max_retries,
                },
            )
        else:
            step.status = StepStatus.FAILED
            step.completed_at = time.time()

            self.queue.publish(
                f"workflow.step.{step.step_type}.failed",
                {
                    "workflow_id": workflow.workflow_id,
                    "step_id": step.step_id,
                    "error": error,
                    "retry_count": step.retry_count,
                },
            )

            self._fail_workflow(workflow, f"Step {step.step_id} failed: {error}")

    def _is_workflow_complete(self, workflow: WorkflowInstance) -> bool:
        """Check if workflow is complete."""
        for step in workflow.steps.values():
            if step.status in [StepStatus.PENDING, StepStatus.RUNNING]:
                return False
        return True

    def _complete_workflow(self, workflow: WorkflowInstance):
        """Mark workflow as completed."""
        workflow.status = WorkflowStatus.COMPLETED
        workflow.completed_at = time.time()
        self.running_workflows[workflow.workflow_id] = False

        total_duration = workflow.completed_at - workflow.started_at
        completed_steps = sum(
            1 for step in workflow.steps.values() if step.status == StepStatus.COMPLETED
        )

        self.queue.publish(
            f"workflow.{workflow.workflow_name}.completed",
            {
                "workflow_id": workflow.workflow_id,
                "workflow_name": workflow.workflow_name,
                "total_duration": total_duration,
                "steps_completed": completed_steps,
                "steps_total": len(workflow.steps),
            },
        )

    def _fail_workflow(self, workflow: WorkflowInstance, error: str):
        """Mark workflow as failed."""
        workflow.status = WorkflowStatus.FAILED
        workflow.completed_at = time.time()
        self.running_workflows[workflow.workflow_id] = False

        failed_step = None
        for step in workflow.steps.values():
            if step.status == StepStatus.FAILED:
                failed_step = step.step_id
                break

        self.queue.publish(
            f"workflow.{workflow.workflow_name}.failed",
            {
                "workflow_id": workflow.workflow_id,
                "workflow_name": workflow.workflow_name,
                "error": error,
                "failed_step": failed_step,
            },
        )

    # Built-in step processors
    def _process_http_request_step(
        self, workflow: WorkflowInstance, step: WorkflowStep
    ) -> Dict[str, Any]:
        """Process HTTP request step."""
        url = step.config.get("url", "https://api.example.com/data")
        method = step.config.get("method", "GET")

        request_time = random.uniform(0.1, 0.5)
        time.sleep(request_time)

        if random.random() < 0.1:
            raise Exception(f"HTTP {method} request to {url} failed: timeout")

        return {
            "status_code": random.choice([200, 200, 200, 404, 500]),
            "response_time": request_time,
            "data_size": random.randint(100, 5000),
        }

    def _process_data_validation_step(
        self, workflow: WorkflowInstance, step: WorkflowStep
    ) -> Dict[str, Any]:
        """Process data validation step."""
        time.sleep(random.uniform(0.05, 0.2))

        is_valid = random.random() > 0.15

        if not is_valid:
            raise Exception("Data validation failed: missing required fields")

        return {
            "validation_passed": is_valid,
            "records_validated": random.randint(10, 1000),
            "schema_version": "v1.2",
        }

    def _process_transformation_step(
        self, workflow: WorkflowInstance, step: WorkflowStep
    ) -> Dict[str, Any]:
        """Process data transformation step."""
        transformation_type = step.config.get("type", "map")
        input_format = step.config.get("input_format", "json")
        output_format = step.config.get("output_format", "json")

        time.sleep(random.uniform(0.1, 0.4))

        return {
            "transformation_type": transformation_type,
            "input_format": input_format,
            "output_format": output_format,
            "records_transformed": random.randint(50, 500),
        }

    def _process_notification_step(
        self, workflow: WorkflowInstance, step: WorkflowStep
    ) -> Dict[str, Any]:
        """Process notification step."""
        notification_type = step.config.get("type", "email")
        recipients = step.config.get("recipients", [])

        time.sleep(random.uniform(0.05, 0.15))

        return {
            "notification_type": notification_type,
            "recipients_count": len(recipients),
            "delivery_status": "sent",
            "message_id": f"msg_{int(time.time())}",
        }

    def _process_approval_step(
        self, workflow: WorkflowInstance, step: WorkflowStep
    ) -> Dict[str, Any]:
        """Process approval step (simulated auto-approval)."""
        approver = step.config.get("approver", "system")

        time.sleep(random.uniform(0.1, 0.3))

        approved = random.random() > 0.2

        if not approved:
            raise Exception(f"Approval denied by {approver}")

        return {
            "approved": approved,
            "approver": approver,
            "approval_time": time.time(),
            "comments": "Auto-approved by system",
        }

    def _process_condition_step(
        self, workflow: WorkflowInstance, step: WorkflowStep
    ) -> Dict[str, Any]:
        """Process conditional logic step."""
        condition_expr = step.config.get("condition", "true")
        context_var = step.config.get("context_variable", "status")

        time.sleep(random.uniform(0.01, 0.05))

        context_value = workflow.context.get(context_var, None)
        result = (
            bool(context_value)
            if context_value is not None
            else random.choice([True, False])
        )

        self.queue.publish(
            f"condition.{step.step_type}.evaluated",
            {
                "condition_id": step.step_id,
                "expression": condition_expr,
                "context_variable": context_var,
                "context_value": context_value,
                "result": result,
            },
        )

        return {
            "condition_result": result,
            "expression": condition_expr,
            "context_value": context_value,
        }

    def _process_delay_step(
        self, workflow: WorkflowInstance, step: WorkflowStep
    ) -> Dict[str, Any]:
        """Process delay step."""
        delay_seconds = step.config.get("delay_seconds", 1.0)
        time.sleep(delay_seconds)
        return {"delay_duration": delay_seconds, "completed_at": time.time()}

    def _process_parallel_branch_step(
        self, workflow: WorkflowInstance, step: WorkflowStep
    ) -> Dict[str, Any]:
        """Process parallel branch step."""
        branch_count = step.config.get("branches", 2)
        time.sleep(random.uniform(0.2, 0.6))
        return {
            "branches_executed": branch_count,
            "parallel_execution": True,
            "completion_time": time.time(),
        }


def create_sample_workflows() -> List[Dict[str, Any]]:
    """Create sample workflow definitions."""

    data_workflow = {
        "name": "data_processing",
        "steps": [
            {
                "step_id": "fetch_data",
                "step_type": "http_request",
                "name": "Fetch Data from API",
                "config": {
                    "url": "https://api.data-source.com/dataset",
                    "method": "GET",
                },
                "dependencies": [],
            },
            {
                "step_id": "validate_data",
                "step_type": "data_validation",
                "name": "Validate Data Quality",
                "config": {"schema": {"required": ["id", "value"]}},
                "dependencies": ["fetch_data"],
            },
            {
                "step_id": "transform_data",
                "step_type": "transformation",
                "name": "Transform Data Format",
                "config": {
                    "type": "normalize",
                    "input_format": "json",
                    "output_format": "parquet",
                },
                "dependencies": ["validate_data"],
            },
            {
                "step_id": "check_quality",
                "step_type": "condition",
                "name": "Check Data Quality",
                "config": {
                    "condition": "quality_score > 0.8",
                    "context_variable": "quality",
                },
                "dependencies": ["transform_data"],
            },
            {
                "step_id": "notify_completion",
                "step_type": "notification",
                "name": "Notify Completion",
                "config": {"type": "email", "recipients": ["admin@company.com"]},
                "dependencies": ["check_quality"],
            },
        ],
    }

    order_workflow = {
        "name": "order_processing",
        "steps": [
            {
                "step_id": "validate_order",
                "step_type": "data_validation",
                "name": "Validate Order Data",
                "config": {"schema": {"required": ["customer_id", "items", "total"]}},
                "dependencies": [],
            },
            {
                "step_id": "check_inventory",
                "step_type": "http_request",
                "name": "Check Inventory",
                "config": {"url": "https://inventory.api.com/check", "method": "POST"},
                "dependencies": ["validate_order"],
            },
            {
                "step_id": "approve_order",
                "step_type": "approval",
                "name": "Approve Order",
                "config": {"approver": "order_manager", "timeout": 300},
                "dependencies": ["check_inventory"],
            },
            {
                "step_id": "process_payment",
                "step_type": "http_request",
                "name": "Process Payment",
                "config": {"url": "https://payment.api.com/charge", "method": "POST"},
                "dependencies": ["approve_order"],
            },
            {
                "step_id": "fulfill_order",
                "step_type": "parallel_branch",
                "name": "Fulfill Order",
                "config": {"branches": 3},
                "dependencies": ["process_payment"],
            },
            {
                "step_id": "send_confirmation",
                "step_type": "notification",
                "name": "Send Order Confirmation",
                "config": {"type": "email", "recipients": ["customer@email.com"]},
                "dependencies": ["fulfill_order"],
            },
        ],
    }

    maintenance_workflow = {
        "name": "system_maintenance",
        "steps": [
            {
                "step_id": "pre_check",
                "step_type": "condition",
                "name": "Pre-maintenance Check",
                "config": {
                    "condition": "system_load < 0.5",
                    "context_variable": "load",
                },
                "dependencies": [],
            },
            {
                "step_id": "notify_downtime",
                "step_type": "notification",
                "name": "Notify Scheduled Downtime",
                "config": {"type": "broadcast", "recipients": ["ops-team@company.com"]},
                "dependencies": ["pre_check"],
            },
            {
                "step_id": "wait_period",
                "step_type": "delay",
                "name": "Wait for Maintenance Window",
                "config": {"delay_seconds": 0.5},
                "dependencies": ["notify_downtime"],
            },
            {
                "step_id": "backup_data",
                "step_type": "http_request",
                "name": "Backup Critical Data",
                "config": {"url": "https://backup.api.com/snapshot", "method": "POST"},
                "dependencies": ["wait_period"],
            },
            {
                "step_id": "apply_updates",
                "step_type": "transformation",
                "name": "Apply System Updates",
                "config": {"type": "system_update"},
                "dependencies": ["backup_data"],
            },
            {
                "step_id": "post_check",
                "step_type": "data_validation",
                "name": "Post-maintenance Validation",
                "config": {"schema": {"required": ["health_status", "response_time"]}},
                "dependencies": ["apply_updates"],
            },
            {
                "step_id": "notify_completion",
                "step_type": "notification",
                "name": "Notify Maintenance Complete",
                "config": {"type": "broadcast", "recipients": ["ops-team@company.com"]},
                "dependencies": ["post_check"],
            },
        ],
    }

    return [data_workflow, order_workflow, maintenance_workflow]


def main():
    """Demo event-driven workflow engine."""
    print("Event-Driven Workflow Engine")
    print("=" * 50)

    # Create message queue and executor
    queue = MessageQueue()
    executor = Executor(mode=ExecutionMode.THREAD, max_workers=6)

    # Create workflow engine
    engine = WorkflowEngine("main_engine", queue)

    # Create sample workflows
    workflow_definitions = create_sample_workflows()

    print("Creating and starting workflows...")

    # Create workflow instances
    workflow_ids = []
    for workflow_def in workflow_definitions:
        workflow_id = engine.create_workflow(
            workflow_def["name"], workflow_def["steps"]
        )
        workflow_ids.append((workflow_id, workflow_def["name"]))

    print(f"Created {len(workflow_ids)} workflow instances\n")

    # Start workflows with different triggers and contexts
    for workflow_id, workflow_name in workflow_ids:
        trigger = "scheduled" if "maintenance" in workflow_name else "api_request"
        context = {
            "environment": "production",
            "quality": random.uniform(0.7, 0.95),
            "load": random.uniform(0.1, 0.8),
            "user_id": f"user_{random.randint(1000, 9999)}",
        }
        engine.start_workflow(workflow_id, trigger, context)

    # Execute workflows using executor
    print("\nExecuting workflows in parallel...")
    start_time = time.time()

    with executor:
        task_ids = []
        for wf_id, _ in workflow_ids:
            task_id = executor.submit(engine.execute_workflow, wf_id)
            task_ids.append(task_id)

        results = [executor.result(tid) for tid in task_ids]

    total_execution_time = time.time() - start_time

    # Analyze results
    print(f"\n{'=' * 50}")
    print("Workflow Execution Summary:")

    successful_workflows = 0
    failed_workflows = 0
    total_steps_completed = 0

    for (workflow_id, workflow_name), result in zip(workflow_ids, results):
        workflow = engine.workflows[workflow_id]

        if workflow.status == WorkflowStatus.COMPLETED:
            successful_workflows += 1
            workflow_duration = workflow.completed_at - workflow.started_at

            completed_steps = sum(
                1
                for step in workflow.steps.values()
                if step.status == StepStatus.COMPLETED
            )
            total_steps_completed += completed_steps

            print(
                f"  [OK] {workflow_name}: {completed_steps} steps in {workflow_duration:.2f}s"
            )
        else:
            failed_workflows += 1
            print(f"  [FAIL] {workflow_name}: {workflow.status.value}")

    print(f"\nOverall Statistics:")
    print(f"  Successful workflows: {successful_workflows}/{len(workflow_ids)}")
    print(f"  Failed workflows: {failed_workflows}")
    print(f"  Total steps completed: {total_steps_completed}")
    print(f"  Total execution time: {total_execution_time:.2f}s")

    # Step type statistics
    step_type_stats: Dict[str, Dict[str, int]] = {}
    for workflow in engine.workflows.values():
        for step in workflow.steps.values():
            step_type = step.step_type
            if step_type not in step_type_stats:
                step_type_stats[step_type] = {"completed": 0, "failed": 0, "total": 0}

            step_type_stats[step_type]["total"] += 1
            if step.status == StepStatus.COMPLETED:
                step_type_stats[step_type]["completed"] += 1
            elif step.status == StepStatus.FAILED:
                step_type_stats[step_type]["failed"] += 1

    print(f"\nStep Type Performance:")
    for step_type, stats in step_type_stats.items():
        success_rate = (
            (stats["completed"] / stats["total"] * 100) if stats["total"] > 0 else 0
        )
        print(
            f"  {step_type}: {stats['completed']}/{stats['total']} ({success_rate:.0f}% success)"
        )

    print(f"\nWorkflow Engine demonstrates:")
    print(f"  - Event-driven step orchestration via MessageQueue")
    print(f"  - Dependency-based execution order")
    print(f"  - Parallel workflow execution with Executor")
    print(f"  - Step retry and error handling")
    print(f"  - Conditional logic and branching")


if __name__ == "__main__":
    main()
