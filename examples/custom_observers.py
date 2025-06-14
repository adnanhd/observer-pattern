#!/usr/bin/env python3
"""
Custom Observers Example
Demonstrates building domain-specific observers for specialized monitoring.
"""

import random
import time
from collections import defaultdict

from callpyback import CallPyBack
from callpyback.core.state_machine import ExecutionState
from callpyback.observers.base import BaseObserver


class MLWorkflowObserver(BaseObserver):
    """Custom observer for machine learning workflow monitoring."""

    def __init__(self):
        super().__init__(priority=90, name="MLWorkflow")
        self.model_metrics = {}
        self.training_history = []
        self.inference_stats = defaultdict(list)
        self.experiments = defaultdict(list)

    def update(self, context):
        """Handle ML workflow events."""
        if context.state == ExecutionState.COMPLETED:
            operation = context.arguments.get("operation", "unknown")

            if operation == "train":
                self._handle_training(context)
            elif operation == "predict":
                self._handle_inference(context)
            elif operation == "evaluate":
                self._handle_evaluation(context)
            elif operation == "experiment":
                self._handle_experiment(context)

    def _handle_training(self, context):
        """Handle model training events."""
        if context.is_successful and context.local_variables:
            epoch = context.local_variables.get("epoch", 0)
            model_metrics = {
                "epoch": epoch,
                "accuracy": context.local_variables.get("accuracy", 0),
                "loss": context.local_variables.get("loss", float("inf")),
                "learning_rate": context.local_variables.get("learning_rate", 0.001),
                "timestamp": context.timestamp,
                "execution_time": getattr(context.result, "execution_time", 0),
            }

            self.training_history.append(model_metrics)

            # Training progress analysis
            if len(self.training_history) > 1:
                prev_metrics = self.training_history[-2]
                acc_improvement = model_metrics["accuracy"] - prev_metrics["accuracy"]
                loss_improvement = prev_metrics["loss"] - model_metrics["loss"]

                if acc_improvement > 0.05:
                    print(
                        f"📊 TRAINING: Significant accuracy improvement! "
                        f"Epoch {epoch}: {model_metrics['accuracy']:.3f} "
                        f"(+{acc_improvement:.3f})"
                    )
                elif acc_improvement < -0.02:
                    print(f"⚠️  TRAINING: Accuracy degradation at epoch {epoch}")

            print(
                f"📈 Training Epoch {epoch}: "
                f"Accuracy={model_metrics['accuracy']:.3f}, "
                f"Loss={model_metrics['loss']:.3f}"
            )

    def _handle_inference(self, context):
        """Handle model inference events."""
        if context.result and hasattr(context.result, "execution_time"):
            model_name = context.arguments.get("model_name", "default")
            batch_size = context.arguments.get("batch_size", 1)
            inference_time = context.result.execution_time

            self.inference_stats[model_name].append(
                {
                    "time": inference_time,
                    "batch_size": batch_size,
                    "throughput": (
                        batch_size / inference_time if inference_time > 0 else 0
                    ),
                }
            )

            # Performance alerts
            if inference_time > 0.1:
                print(
                    f"🔍 SLOW INFERENCE: {model_name} took {inference_time*1000:.0f}ms "
                    f"for batch size {batch_size}"
                )

    def _handle_evaluation(self, context):
        """Handle model evaluation events."""
        if context.is_successful and context.result:
            model_name = context.arguments.get("model_name", "default")
            metrics = context.result.value if hasattr(context.result, "value") else {}

            self.model_metrics[model_name] = {
                **metrics,
                "timestamp": context.timestamp,
                "evaluation_time": getattr(context.result, "execution_time", 0),
            }

            print(f"📈 EVALUATION: {model_name} - {metrics}")

    def _handle_experiment(self, context):
        """Handle experiment tracking."""
        if context.is_successful:
            experiment_id = context.arguments.get("experiment_id", "unknown")
            hyperparams = context.arguments.get("hyperparams", {})

            if context.local_variables:
                experiment_data = {
                    "experiment_id": experiment_id,
                    "hyperparams": hyperparams,
                    "final_accuracy": context.local_variables.get("final_accuracy", 0),
                    "best_loss": context.local_variables.get("best_loss", float("inf")),
                    "epochs": context.local_variables.get("epochs", 0),
                    "timestamp": context.timestamp,
                }

                self.experiments[experiment_id].append(experiment_data)
                print(
                    f"🧪 EXPERIMENT: {experiment_id} completed - "
                    f"Accuracy: {experiment_data['final_accuracy']:.3f}"
                )

    def get_ml_summary(self):
        """Generate ML workflow summary."""
        # Calculate average inference times
        avg_inference_times = {}
        for model, stats in self.inference_stats.items():
            if stats:
                avg_time = sum(s["time"] for s in stats) / len(stats)
                avg_throughput = sum(s["throughput"] for s in stats) / len(stats)
                avg_inference_times[model] = {
                    "avg_time_ms": avg_time * 1000,
                    "avg_throughput": avg_throughput,
                    "total_inferences": len(stats),
                }

        # Find best experiment
        best_experiment = None
        best_accuracy = 0

        for exp_id, experiments in self.experiments.items():
            for exp in experiments:
                if exp["final_accuracy"] > best_accuracy:
                    best_accuracy = exp["final_accuracy"]
                    best_experiment = exp

        return {
            "training_epochs": len(self.training_history),
            "models_evaluated": len(self.model_metrics),
            "inference_models": len(self.inference_stats),
            "experiments_run": sum(len(exps) for exps in self.experiments.values()),
            "avg_inference_times": avg_inference_times,
            "latest_metrics": self.model_metrics,
            "best_experiment": best_experiment,
        }


class FinancialAuditObserver(BaseObserver):
    """Custom observer for financial transaction auditing."""

    def __init__(self):
        super().__init__(priority=95, name="FinancialAudit")
        self.transactions = []
        self.suspicious_activity = []
        self.daily_totals = defaultdict(lambda: defaultdict(float))
        self.user_activity = defaultdict(list)

    def update(self, context):
        """Audit financial transactions."""
        if context.state == ExecutionState.COMPLETED and context.arguments.get(
            "transaction_type"
        ):

            self._audit_transaction(context)

    def _audit_transaction(self, context):
        """Comprehensive transaction auditing."""
        transaction = {
            "timestamp": context.timestamp,
            "reference": f"TXN_{len(self.transactions)+1:06d}",
            "type": context.arguments.get("transaction_type"),
            "amount": context.arguments.get("amount", 0),
            "user_id": context.arguments.get("user_id"),
            "account_from": context.arguments.get("account_from"),
            "account_to": context.arguments.get("account_to"),
            "success": context.is_successful,
            "execution_time": (
                getattr(context.result, "execution_time", 0) if context.result else 0
            ),
        }

        if context.is_failed:
            transaction["failure_reason"] = str(context.result.exception)
            transaction["error_type"] = context.result.exception_type.__name__

        self.transactions.append(transaction)

        # Track user activity
        self.user_activity[transaction["user_id"]].append(transaction)

        # Track daily totals by transaction type
        day_key = time.strftime("%Y-%m-%d", time.localtime(context.timestamp))
        if transaction["success"]:
            self.daily_totals[day_key][transaction["type"]] += transaction["amount"]

        # Comprehensive suspicious activity detection
        if self._is_suspicious(transaction):
            self.suspicious_activity.append(transaction)
            print(
                f"🚨 SUSPICIOUS TRANSACTION: {transaction['reference']} - "
                f"${transaction['amount']:.2f} {transaction['type']} by {transaction['user_id']}"
            )

        # Real-time compliance monitoring
        if transaction["amount"] > 10000 and transaction["success"]:
            print(
                f"💰 HIGH-VALUE TRANSACTION: {transaction['reference']} - "
                f"${transaction['amount']:.2f} requires compliance review"
            )

    def _is_suspicious(self, transaction):
        """Advanced suspicious activity detection."""
        user_id = transaction["user_id"]
        amount = transaction["amount"]

        # Large transaction amount threshold
        if amount > 50000:
            return True

        # High frequency transactions from same user
        user_recent = [
            t
            for t in self.user_activity[user_id][-10:]
            if time.time() - t["timestamp"] < 300
        ]  # Last 5 minutes

        if len(user_recent) >= 5:
            return True

        # Unusual transaction patterns
        user_transactions = self.user_activity[user_id]
        if len(user_transactions) > 1:
            # Check for round number patterns (possible structuring)
            if amount % 1000 == 0 and amount < 10000:
                recent_round = sum(
                    1 for t in user_transactions[-5:] if t["amount"] % 1000 == 0
                )
                if recent_round >= 3:
                    return True

            # Check for rapid escalation in transaction amounts
            recent_amounts = [t["amount"] for t in user_transactions[-3:]]
            if len(recent_amounts) >= 3:
                if all(
                    recent_amounts[i] < recent_amounts[i + 1] * 0.5
                    for i in range(len(recent_amounts) - 1)
                ):
                    return True

        return False

    def get_financial_summary(self):
        """Generate comprehensive financial audit summary."""
        total_transactions = len(self.transactions)
        successful_transactions = sum(1 for t in self.transactions if t["success"])
        total_amount = sum(t["amount"] for t in self.transactions if t["success"])

        # Transaction type breakdown
        type_breakdown = defaultdict(lambda: {"count": 0, "total": 0})
        for txn in self.transactions:
            if txn["success"]:
                type_breakdown[txn["type"]]["count"] += 1
                type_breakdown[txn["type"]]["total"] += txn["amount"]

        # User risk analysis
        high_risk_users = []
        for user_id, transactions in self.user_activity.items():
            user_total = sum(t["amount"] for t in transactions if t["success"])
            user_suspicious = sum(
                1
                for t in transactions
                if any(
                    s["reference"] == t["reference"] for s in self.suspicious_activity
                )
            )

            if user_suspicious > 0 or user_total > 100000:
                high_risk_users.append(
                    {
                        "user_id": user_id,
                        "total_amount": user_total,
                        "transaction_count": len(transactions),
                        "suspicious_count": user_suspicious,
                    }
                )

        return {
            "total_transactions": total_transactions,
            "successful_transactions": successful_transactions,
            "failed_transactions": total_transactions - successful_transactions,
            "total_amount": total_amount,
            "suspicious_activity": len(self.suspicious_activity),
            "success_rate": (successful_transactions / max(total_transactions, 1))
            * 100,
            "transaction_types": dict(type_breakdown),
            "daily_totals": {
                day: dict(types) for day, types in self.daily_totals.items()
            },
            "high_risk_users": high_risk_users,
            "compliance_flags": len(
                [t for t in self.transactions if t["success"] and t["amount"] > 10000]
            ),
        }


# Setup custom observers
ml_observer = MLWorkflowObserver()
financial_observer = FinancialAuditObserver()


# ML workflow functions
@CallPyBack(
    observers=[ml_observer],
    variable_names=[
        "epoch",
        "accuracy",
        "loss",
        "learning_rate",
        "final_accuracy",
        "best_loss",
        "epochs",
    ],
    exception_classes=(ValueError, RuntimeError),
    default_return={"status": "ml_operation_failed"},
)
def ml_operation(operation, model_name="default", **kwargs):
    """ML operations with comprehensive monitoring."""

    if operation == "train":
        epoch_data = kwargs.get("epoch_data", {})
        epoch = epoch_data.get("epoch", 0)
        learning_rate = epoch_data.get("learning_rate", 0.001)

        # Simulate training with realistic metrics progression
        base_accuracy = min(0.95, 0.5 + (epoch * 0.04))
        accuracy = base_accuracy + random.uniform(-0.05, 0.05)

        base_loss = max(0.05, 2.0 - (epoch * 0.12))
        loss = base_loss + random.uniform(-0.1, 0.1)

        # Simulate training instability
        if accuracy < 0.4 or loss > 3.0:
            raise ValueError(f"Training diverged at epoch {epoch}")

        return {
            "status": "training_complete",
            "epoch": epoch,
            "accuracy": accuracy,
            "loss": loss,
            "model": model_name,
        }

    elif operation == "predict":
        batch_size = kwargs.get("batch_size", 32)
        # Simulate variable inference time based on batch size
        time.sleep(random.uniform(0.01, 0.05) * (batch_size / 32))

        predictions = [f"class_{random.randint(0, 9)}" for _ in range(batch_size)]
        confidences = [random.uniform(0.7, 0.99) for _ in range(batch_size)]

        return {
            "status": "inference_complete",
            "predictions": predictions,
            "confidences": confidences,
            "batch_size": batch_size,
        }

    elif operation == "evaluate":
        # Simulate comprehensive model evaluation
        time.sleep(random.uniform(0.02, 0.08))

        metrics = {
            "accuracy": random.uniform(0.85, 0.95),
            "precision": random.uniform(0.80, 0.90),
            "recall": random.uniform(0.75, 0.90),
            "f1_score": random.uniform(0.78, 0.92),
            "auc": random.uniform(0.85, 0.98),
        }

        return metrics

    elif operation == "experiment":
        experiment_id = kwargs.get("experiment_id", "exp_unknown")
        hyperparams = kwargs.get("hyperparams", {})

        # Simulate hyperparameter experiment
        epochs = hyperparams.get("epochs", 10)

        # Simulate training progression
        final_accuracy = 0.5
        best_loss = 2.0

        for epoch in range(epochs):
            epoch_acc = min(0.95, 0.5 + (epoch * 0.04) + random.uniform(-0.02, 0.02))
            epoch_loss = max(0.05, 2.0 - (epoch * 0.1) + random.uniform(-0.05, 0.05))

            final_accuracy = max(final_accuracy, epoch_acc)
            best_loss = min(best_loss, epoch_loss)

        return {
            "status": "experiment_complete",
            "experiment_id": experiment_id,
            "final_accuracy": final_accuracy,
            "hyperparams": hyperparams,
        }


# Financial transaction function
@CallPyBack(
    observers=[financial_observer],
    exception_classes=(ValueError, PermissionError, RuntimeError),
    default_return={"status": "transaction_failed", "amount": 0},
)
def financial_transaction(transaction_type, user_id, amount, **kwargs):
    """Financial transaction with comprehensive auditing."""

    # Input validation
    if amount <= 0:
        raise ValueError("Transaction amount must be positive")

    # Business rule validation
    if transaction_type == "withdrawal" and amount > 50000:
        if user_id != "premium_user":
            raise PermissionError("Withdrawal limit exceeded for regular users")

    # Simulate transaction processing with realistic delays
    processing_time = random.uniform(0.01, 0.05)
    if amount > 10000:
        processing_time += random.uniform(
            0.02, 0.08
        )  # Additional processing for large amounts

    time.sleep(processing_time)

    # Simulate failure scenarios
    failure_rate = 0.03  # Base 3% failure rate
    if amount > 100000:
        failure_rate = 0.08  # Higher failure rate for very large amounts

    if random.random() < failure_rate:
        raise RuntimeError("Transaction processing error")

    return {
        "status": "success",
        "transaction_type": transaction_type,
        "amount": amount,
        "processed_at": time.time(),
        "processing_time": processing_time,
    }


if __name__ == "__main__":
    # ML workflow simulation
    print("1. Running ML workflow simulation...")

    # Training simulation
    model_name = "sentiment_classifier"
    for epoch in range(12):
        try:
            result = ml_operation(
                "train", model_name, epoch_data={"epoch": epoch, "learning_rate": 0.001}
            )

            if isinstance(result, dict) and result.get("accuracy", 0) > 0.92:
                print(f"✅ Training target reached at epoch {epoch}")
                break
        except ValueError as e:
            print(f"❌ Training failed: {e}")
            break

    # Inference simulation
    print("  Running inference tests...")
    for batch_size in [1, 16, 32, 64, 128]:
        ml_operation("predict", model_name, batch_size=batch_size)

    # Model evaluation
    print("  Running model evaluation...")
    ml_operation("evaluate", model_name)

    # Hyperparameter experiments
    print("  Running hyperparameter experiments...")
    experiments = [
        {
            "experiment_id": "exp_lr_001",
            "hyperparams": {"learning_rate": 0.01, "epochs": 8},
        },
        {
            "experiment_id": "exp_lr_0001",
            "hyperparams": {"learning_rate": 0.001, "epochs": 10},
        },
        {"experiment_id": "exp_dropout", "hyperparams": {"dropout": 0.3, "epochs": 12}},
    ]

    for exp_config in experiments:
        ml_operation("experiment", model_name, **exp_config)

    # Financial transaction simulation
    print("\n2. Running financial transaction simulation...")

    transaction_scenarios = [
        # Normal operations
        ("deposit", "user001", 1500.00),
        ("withdrawal", "user002", 800.00),
        ("transfer", "user001", 250.00),
        # Large transactions
        ("deposit", "user003", 25000.00),
        ("withdrawal", "premium_user", 75000.00),
        # Suspicious patterns - high frequency
        *[
            ("transfer", "user004", 999.00) for _ in range(4)
        ],  # Just under 1000 - structuring
        # Escalating amounts - suspicious
        ("transfer", "user005", 1000.00),
        ("transfer", "user005", 3000.00),
        ("transfer", "user005", 9000.00),
        # Very large transaction
        ("wire_transfer", "user006", 150000.00),
        # Failed transactions
        ("withdrawal", "user007", 60000.00),  # Over limit
        ("transfer", "user008", -500.00),  # Invalid amount
    ]

    for txn_type, user, amount in transaction_scenarios:
        try:
            result = financial_transaction(
                txn_type,
                user,
                amount,
                account_from=f"{user}_checking",
                account_to="external_account" if "transfer" in txn_type else None,
            )
        except Exception as e:
            print(f"Transaction failed: {e}")

    # Generate comprehensive reports
    print("\n" + "=" * 60)
    print("CUSTOM OBSERVERS ANALYSIS REPORT")
    print("=" * 60)

    ml_summary = ml_observer.get_ml_summary()
    financial_summary = financial_observer.get_financial_summary()

    print(f"ML Workflow Summary:")
    print(f"  Training epochs completed: {ml_summary['training_epochs']}")
    print(f"  Models evaluated: {ml_summary['models_evaluated']}")
    print(f"  Experiments run: {ml_summary['experiments_run']}")
    print(f"  Inference models: {ml_summary['inference_models']}")

    if ml_summary["best_experiment"]:
        best = ml_summary["best_experiment"]
        print(
            f"  Best experiment: {best['experiment_id']} "
            f"(accuracy: {best['final_accuracy']:.3f})"
        )

    print(f"  Average inference performance:")
    for model, stats in ml_summary["avg_inference_times"].items():
        print(
            f"    {model}: {stats['avg_time_ms']:.1f}ms/inference, "
            f"{stats['avg_throughput']:.1f} samples/sec"
        )

    print(f"\nFinancial Audit Summary:")
    print(f"  Total transactions: {financial_summary['total_transactions']}")
    print(f"  Success rate: {financial_summary['success_rate']:.1f}%")
    print(f"  Total amount processed: ${financial_summary['total_amount']:,.2f}")
    print(
        f"  Suspicious activities detected: {financial_summary['suspicious_activity']}"
    )
    print(f"  Compliance flags: {financial_summary['compliance_flags']}")

    print(f"  Transaction breakdown:")
    for txn_type, stats in financial_summary["transaction_types"].items():
        print(
            f"    {txn_type}: {stats['count']} transactions, "
            f"${stats['total']:,.2f} total"
        )

    if financial_summary["high_risk_users"]:
        print(
            f"  High-risk users identified: {len(financial_summary['high_risk_users'])}"
        )
        for user in financial_summary["high_risk_users"][:3]:  # Show top 3
            print(
                f"    {user['user_id']}: ${user['total_amount']:,.2f}, "
                f"{user['suspicious_count']} suspicious transactions"
            )
