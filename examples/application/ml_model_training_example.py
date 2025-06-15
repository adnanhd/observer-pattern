#!/usr/bin/env python3
"""
Parallel ML Model Training - Application Example
Demonstrates compute-intensive machine learning with multiprocessing.
"""

import math
import random
import time
from dataclasses import dataclass
from typing import Dict, List

from callpyback import ExecutionMode, emit_event, on_event, plugin_session


@dataclass
class MLDataset:
    name: str
    features: int
    samples: int
    target_type: str  # 'classification' or 'regression'


@dataclass
class ModelConfig:
    model_type: str
    hyperparameters: Dict
    dataset: MLDataset


# ML training event handlers
@on_event("ml.training.started")
def handle_training_started(message):
    payload = message.payload
    model = payload.get("model_type", "unknown")
    dataset = payload.get("dataset_name", "unknown")
    print(f"🧠 Training started: {model} on {dataset}")


@on_event("ml.training.completed")
def handle_training_completed(message):
    payload = message.payload
    model = payload.get("model_type", "unknown")
    accuracy = payload.get("accuracy", 0)
    training_time = payload.get("training_time", 0)
    print(f"✅ {model} completed: {accuracy:.3f} accuracy in {training_time:.2f}s")


@on_event("ml.training.failed")
def handle_training_failed(message):
    model = message.payload.get("model_type", "unknown")
    error = message.payload.get("error", "Unknown error")
    print(f"❌ {model} failed: {error}")


@on_event("ml.hyperparameter.*.completed")
def handle_hyperparameter_search(message):
    """Handle hyperparameter search results"""
    search_type = message.topic.split(".")[2]
    payload = message.payload
    best_score = payload.get("best_score", 0)
    print(f"🔍 {search_type} search completed: best score {best_score:.3f}")


def simulate_model_training(config: ModelConfig) -> Dict:
    """Simulate CPU-intensive model training"""

    emit_event(
        "ml.training.started",
        {
            "model_type": config.model_type,
            "dataset_name": config.dataset.name,
            "features": config.dataset.features,
            "samples": config.dataset.samples,
        },
    )

    start_time = time.time()

    try:
        # Simulate compute-intensive training
        # Base training time depends on model complexity
        base_times = {
            "neural_network": 2.0,
            "random_forest": 1.0,
            "svm": 1.5,
            "gradient_boosting": 1.8,
            "linear_regression": 0.5,
            "logistic_regression": 0.7,
        }

        base_time = base_times.get(config.model_type, 1.0)

        # Scale by dataset size and features
        complexity_factor = (config.dataset.samples * config.dataset.features) / 100000
        training_time = base_time * (1 + complexity_factor)

        # Simulate actual CPU work (mathematical operations)
        iterations = int(training_time * 1000)
        result = 0
        for i in range(iterations):
            # Complex mathematical operations to consume CPU
            result += math.sin(i) * math.cos(i) * math.sqrt(i + 1)
            if i % 10000 == 0:
                time.sleep(0.001)  # Brief yield to prevent blocking

        # Random training failure (5% chance)
        if random.random() < 0.05:
            raise ValueError("Training convergence failed")

        # Simulate model performance
        base_accuracy = {
            "neural_network": 0.85,
            "random_forest": 0.82,
            "svm": 0.78,
            "gradient_boosting": 0.84,
            "linear_regression": 0.75,
            "logistic_regression": 0.76,
        }

        accuracy = base_accuracy.get(config.model_type, 0.70)
        accuracy += random.uniform(-0.1, 0.15)  # Random variation
        accuracy = max(0.0, min(1.0, accuracy))  # Clamp to [0,1]

        actual_training_time = time.time() - start_time

        result = {
            "model_type": config.model_type,
            "dataset_name": config.dataset.name,
            "accuracy": accuracy,
            "training_time": actual_training_time,
            "hyperparameters": config.hyperparameters,
            "status": "success",
            "model_size": random.randint(1, 100),  # MB
        }

        emit_event("ml.training.completed", result)
        return result

    except Exception as e:
        error_result = {
            "model_type": config.model_type,
            "dataset_name": config.dataset.name,
            "error": str(e),
            "training_time": time.time() - start_time,
            "status": "failed",
        }

        emit_event("ml.training.failed", error_result)
        return error_result


def hyperparameter_search(
    model_type: str, dataset: MLDataset, search_type: str
) -> Dict:
    """Simulate hyperparameter optimization"""

    # Generate random hyperparameter combinations
    param_combinations = []
    for _ in range(random.randint(5, 12)):
        if model_type == "neural_network":
            params = {
                "learning_rate": random.uniform(0.001, 0.1),
                "hidden_layers": random.randint(1, 4),
                "neurons_per_layer": random.choice([32, 64, 128, 256]),
                "dropout": random.uniform(0.1, 0.5),
            }
        elif model_type == "random_forest":
            params = {
                "n_estimators": random.choice([50, 100, 200, 500]),
                "max_depth": random.choice([None, 5, 10, 20]),
                "min_samples_split": random.randint(2, 10),
                "min_samples_leaf": random.randint(1, 5),
            }
        else:
            params = {
                "param_1": random.uniform(0.1, 1.0),
                "param_2": random.randint(1, 10),
                "param_3": random.choice([True, False]),
            }

        param_combinations.append(params)

    # Simulate training with each combination (CPU intensive)
    best_score = 0
    best_params = {}

    for params in param_combinations:
        config = ModelConfig(model_type, params, dataset)
        result = simulate_model_training(config)

        if result.get("status") == "success":
            score = result.get("accuracy", 0)
            if score > best_score:
                best_score = score
                best_params = params

    search_result = {
        "model_type": model_type,
        "search_type": search_type,
        "best_score": best_score,
        "best_params": best_params,
        "combinations_tried": len(param_combinations),
    }

    emit_event(f"ml.hyperparameter.{search_type}.completed", search_result)
    return search_result


def create_datasets() -> List[MLDataset]:
    """Create sample datasets"""
    return [
        MLDataset("customer_churn", 25, 50000, "classification"),
        MLDataset("house_prices", 15, 30000, "regression"),
        MLDataset("fraud_detection", 45, 100000, "classification"),
        MLDataset("stock_prediction", 20, 75000, "regression"),
        MLDataset("image_classification", 512, 25000, "classification"),
        MLDataset("sales_forecast", 12, 40000, "regression"),
    ]


def main():
    """Demo parallel ML training with multiprocessing"""
    print("🧠 Parallel ML Model Training")
    print("=" * 50)

    datasets = create_datasets()
    model_types = ["neural_network", "random_forest", "svm", "gradient_boosting"]

    # Create training configurations
    training_configs = []
    for dataset in datasets[:4]:  # Use first 4 datasets
        for model_type in model_types[:2]:  # Use 2 model types each
            config = ModelConfig(
                model_type=model_type,
                hyperparameters={"default_lr": 0.01, "batch_size": 32, "epochs": 100},
                dataset=dataset,
            )
            training_configs.append(config)

    with plugin_session() as manager:
        # Configure for CPU-intensive multiprocessing
        manager.configure().processes(4).max_threads(2).execution_mode(
            ExecutionMode.HYBRID
        ).apply()

        print(f"🚀 Training {len(training_configs)} models in parallel...")

        # Train all models in parallel using multiprocessing
        start_time = time.time()
        training_results = manager.map_parallel(
            simulate_model_training, training_configs
        )
        training_duration = time.time() - start_time

        # Analyze training results
        successful_models = [
            r for r in training_results if r.get("status") == "success"
        ]
        failed_models = [r for r in training_results if r.get("status") == "failed"]

        print(f"\n📊 Training Results:")
        print(f"   ✅ Successful: {len(successful_models)}")
        print(f"   ❌ Failed: {len(failed_models)}")
        print(f"   ⏱️ Total time: {training_duration:.2f}s")

        if successful_models:
            avg_accuracy = sum(r.get("accuracy", 0) for r in successful_models) / len(
                successful_models
            )
            best_model = max(successful_models, key=lambda x: x.get("accuracy", 0))
            print(f"   📈 Average accuracy: {avg_accuracy:.3f}")
            print(
                f"   🏆 Best model: {best_model['model_type']} ({best_model['accuracy']:.3f})"
            )

        # Run hyperparameter optimization in parallel
        print(f"\n🔍 Running hyperparameter optimization...")

        search_tasks = [
            (model_types[0], datasets[0], "grid_search"),
            (model_types[1], datasets[1], "random_search"),
            (model_types[0], datasets[2], "bayesian_optimization"),
        ]

        search_results = manager.parallel(
            *[
                lambda mt=mt, ds=ds, st=st: hyperparameter_search(mt, ds, st)
                for mt, ds, st in search_tasks
            ]
        )

        print(f"   Completed {len(search_results)} hyperparameter searches")

        # Show performance metrics
        metrics = manager.get_metrics()
        print(f"\n📈 System Performance:")
        print(f"   Tasks completed: {metrics['tasks_completed']}")
        print(f"   Events published: {metrics['events_published']}")
        print(f"   Health status: {manager.health_check()}")

        if "process_executor" in metrics:
            proc_stats = metrics["process_executor"]
            print(f"   Process pool utilization: {proc_stats}")


if __name__ == "__main__":
    main()
