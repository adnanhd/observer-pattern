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
                # loss_improvement = prev_metrics["loss"] - model_metrics["loss"]

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



# Setup custom observers
ml_observer = MLWorkflowObserver()


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
        epoch = epoch_data.get("epoch", -1)
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



if __name__ == "__main__":
    # ML workflow simulation
    print("1. Running ML workflow simulation...")

    # Training simulation
    model_name = "sentiment_classifier"
    for epoch in range(12):
        try:
            result = ml_operation(
                "train", model_name, epoch_data={"epoch": epoch + 1, "learning_rate": 0.001}
            )

            if isinstance(result, dict) and result.get("accuracy", 0) > 0.92:
                print(f"✅ Training target reached at epoch {epoch + 1}")
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

    # Generate comprehensive reports
    print("\n" + "=" * 60)
    print("CUSTOM OBSERVERS ANALYSIS REPORT")
    print("=" * 60)

    ml_summary = ml_observer.get_ml_summary()

    print("ML Workflow Summary:")
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

    print("  Average inference performance:")
    for model, stats in ml_summary["avg_inference_times"].items():
        print(
            f"    {model}: {stats['avg_time_ms']:.1f}ms/inference, "
            f"{stats['avg_throughput']:.1f} samples/sec"
        )
