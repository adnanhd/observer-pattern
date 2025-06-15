#!/usr/bin/env python3
"""
Uses existing CallPyBack plugins: HybridExecutor, EventBus
"""

import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from callpyback import CallPyBack, on_call, on_failure, on_success
from callpyback.observers.base import BaseObserver
from callpyback.plugins.core.message_queue import EventBus
from callpyback.plugins.executors.hybrid_executor import HybridExecutor


class MLStage(Enum):
    DATA_LOADING = "DATA_LOADING"
    PREPROCESSING = "PREPROCESSING"
    TRAINING = "TRAINING"
    VALIDATION = "VALIDATION"
    PREDICTION = "PREDICTION"


class ModelType(Enum):
    REGRESSION = "REGRESSION"
    CLASSIFICATION = "CLASSIFICATION"
    CLUSTERING = "CLUSTERING"


@dataclass
class Dataset:
    name: str
    features: int
    samples: int
    target_type: str
    quality_score: float = 0.8


@dataclass
class ModelConfig:
    model_type: ModelType
    hyperparameters: Dict[str, Any]
    training_config: Dict[str, Any]


class MLPipelineObserver(BaseObserver):
    """ML pipeline monitoring"""

    def __init__(self):
        super().__init__(priority=95, name="MLPipeline")
        self.stage_metrics = {stage.value: 0 for stage in MLStage}
        self.model_performances = {}
        self.total_training_time = 0.0
        self.errors = 0

    def update(self, context):
        if context.state.name == "COMPLETED" and context.result:
            result = context.result.value
            stage = result.get("stage")
            if stage in self.stage_metrics:
                self.stage_metrics[stage] += 1

            # Track training performance
            if stage == "TRAINING" and "accuracy" in result:
                model_id = result.get("model_id", "unknown")
                self.model_performances[model_id] = result["accuracy"]

            # Track timing
            training_time = result.get("training_time", 0)
            self.total_training_time += training_time

        elif context.state.name == "FAILED":
            self.errors += 1


# Global instances
ml_observer = MLPipelineObserver()
event_bus = EventBus()
hybrid_executor = HybridExecutor(max_threads=2, max_processes=2)


def mock_load_dataset(dataset_name: str) -> Dataset:
    """Mock dataset loading"""
    datasets = {
        "iris": Dataset("iris", 4, 150, "classification", 0.95),
        "housing": Dataset("housing", 13, 506, "regression", 0.85),
        "customers": Dataset("customers", 8, 1000, "clustering", 0.80),
        "sales": Dataset("sales", 10, 2000, "regression", 0.90),
    }

    return datasets.get(
        dataset_name, Dataset("default", 5, 100, "classification", 0.75)
    )


@CallPyBack(
    observers=[
        ml_observer,
        on_call(
            lambda context: print(f"🔄 ML Stage: {context.arguments['stage'].value}")
        ),
        on_success(
            lambda result: event_bus.publish("ml.stage.completed", result.value)
        ),
        on_failure(
            lambda result: event_bus.publish(
                "ml.stage.failed", {"error": str(result.exception)}
            )
        ),
    ]
)
def execute_ml_stage(
    stage: MLStage,
    dataset: Optional[Dataset] = None,
    model_config: Optional[ModelConfig] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute ML pipeline stage"""

    start_time = time.time()

    try:
        if stage == MLStage.DATA_LOADING:
            dataset_name = kwargs.get("dataset_name", "iris")
            loaded_dataset = mock_load_dataset(dataset_name)

            # Simulate loading time
            time.sleep(random.uniform(0.1, 0.3))

            return {
                "stage": stage.value,
                "dataset_name": loaded_dataset.name,
                "features": loaded_dataset.features,
                "samples": loaded_dataset.samples,
                "quality_score": loaded_dataset.quality_score,
                "status": "completed",
            }

        elif stage == MLStage.PREPROCESSING:
            if not dataset:
                raise ValueError("Dataset required for preprocessing")

            # Simulate preprocessing
            time.sleep(random.uniform(0.05, 0.2))

            # Apply preprocessing steps
            steps = kwargs.get(
                "preprocessing_steps", ["normalize", "feature_selection"]
            )
            processed_features = max(
                1, int(dataset.features * 0.8)
            )  # Feature selection

            return {
                "stage": stage.value,
                "original_features": dataset.features,
                "processed_features": processed_features,
                "preprocessing_steps": steps,
                "samples": dataset.samples,
                "quality_improvement": 0.1,
                "status": "completed",
            }

        elif stage == MLStage.TRAINING:
            if not dataset or not model_config:
                raise ValueError("Dataset and model config required for training")

            # Simulate training time (CPU intensive)
            training_time = random.uniform(0.2, 1.0)
            time.sleep(training_time)

            # Mock training results
            base_accuracy = 0.7
            if model_config.model_type == ModelType.CLASSIFICATION:
                accuracy = base_accuracy + random.uniform(0.1, 0.25)
            elif model_config.model_type == ModelType.REGRESSION:
                accuracy = base_accuracy + random.uniform(0.05, 0.2)  # R² score
            else:  # Clustering
                accuracy = base_accuracy + random.uniform(
                    0.05, 0.15
                )  # Silhouette score

            model_id = f"model_{int(time.time() * 1000) % 10000}"

            return {
                "stage": stage.value,
                "model_id": model_id,
                "model_type": model_config.model_type.value,
                "accuracy": round(accuracy, 3),
                "training_time": training_time,
                "hyperparameters": model_config.hyperparameters,
                "status": "completed",
            }

        elif stage == MLStage.VALIDATION:
            model_id = kwargs.get("model_id", "unknown")
            training_accuracy = kwargs.get("training_accuracy", 0.8)

            # Simulate validation
            time.sleep(random.uniform(0.1, 0.3))

            # Validation typically has slightly lower accuracy
            validation_accuracy = training_accuracy * random.uniform(0.85, 0.98)
            overfitting_score = abs(training_accuracy - validation_accuracy)

            return {
                "stage": stage.value,
                "model_id": model_id,
                "validation_accuracy": round(validation_accuracy, 3),
                "training_accuracy": training_accuracy,
                "overfitting_score": round(overfitting_score, 3),
                "is_overfitting": overfitting_score > 0.05,
                "status": "completed",
            }

        elif stage == MLStage.PREDICTION:
            model_id = kwargs.get("model_id", "unknown")
            test_samples = kwargs.get("test_samples", 10)

            # Simulate prediction
            time.sleep(random.uniform(0.02, 0.1))

            # Generate mock predictions
            predictions = [random.uniform(0, 1) for _ in range(test_samples)]
            confidence_scores = [random.uniform(0.6, 0.95) for _ in range(test_samples)]

            return {
                "stage": stage.value,
                "model_id": model_id,
                "predictions": predictions[:5],  # Show first 5
                "confidence_scores": confidence_scores[:5],
                "total_predictions": test_samples,
                "avg_confidence": round(
                    sum(confidence_scores) / len(confidence_scores), 3
                ),
                "status": "completed",
            }

    except Exception as e:
        return {
            "stage": stage.value,
            "status": "failed",
            "error": str(e),
            "execution_time": time.time() - start_time,
        }


class SimpleMLPipeline:
    """Simplified ML pipeline using CallPyBack plugins"""

    def __init__(self):
        self.event_bus = event_bus
        self.executor = hybrid_executor
        self.observer = ml_observer

        # Start services
        self.executor.start()

        # Setup event handlers
        self.event_bus.subscribe("ml.stage.completed", self._on_stage_completed)
        self.event_bus.subscribe("ml.stage.failed", self._on_stage_failed)
        self.event_bus.subscribe("ml.pipeline.completed", self._on_pipeline_completed)

    def _on_stage_completed(self, message):
        """Handle stage completion"""
        payload = message.payload
        stage = payload.get("stage", "unknown")
        print(f"✅ {stage} completed")

        if stage == "TRAINING":
            accuracy = payload.get("accuracy", 0)
            print(f"   Model accuracy: {accuracy}")

    def _on_stage_failed(self, message):
        """Handle stage failure"""
        error = message.payload.get("error", "Unknown error")
        print(f"❌ Stage failed: {error}")

    def _on_pipeline_completed(self, message):
        """Handle pipeline completion"""
        payload = message.payload
        model_id = payload.get("model_id", "unknown")
        final_accuracy = payload.get("final_accuracy", 0)
        print(
            f"🎯 Pipeline completed! Model {model_id} final accuracy: {final_accuracy}"
        )

    def create_model_config(self, model_type: ModelType) -> ModelConfig:
        """Create model configuration"""

        hyperparameter_configs = {
            ModelType.CLASSIFICATION: {
                "n_estimators": random.choice([50, 100, 200]),
                "max_depth": random.choice([3, 5, 10]),
                "learning_rate": random.choice([0.01, 0.1, 0.2]),
            },
            ModelType.REGRESSION: {
                "alpha": random.choice([0.1, 1.0, 10.0]),
                "max_iter": random.choice([100, 500, 1000]),
                "normalize": random.choice([True, False]),
            },
            ModelType.CLUSTERING: {
                "n_clusters": random.choice([2, 3, 5, 8]),
                "init": random.choice(["k-means++", "random"]),
                "max_iter": random.choice([100, 300, 500]),
            },
        }

        training_configs = {
            ModelType.CLASSIFICATION: {
                "validation_split": 0.2,
                "cross_validation": True,
                "stratify": True,
            },
            ModelType.REGRESSION: {
                "validation_split": 0.2,
                "cross_validation": True,
                "normalize_targets": True,
            },
            ModelType.CLUSTERING: {
                "validation_method": "silhouette",
                "distance_metric": "euclidean",
            },
        }

        return ModelConfig(
            model_type=model_type,
            hyperparameters=hyperparameter_configs[model_type],
            training_config=training_configs[model_type],
        )

    def run_pipeline(self, dataset_name: str, model_type: ModelType) -> Dict[str, Any]:
        """Run complete ML pipeline"""

        pipeline_id = f"pipeline_{int(time.time() * 1000) % 10000}"
        print(
            f"🚀 Starting ML pipeline {pipeline_id}: {dataset_name} -> {model_type.value}"
        )

        try:
            # Stage 1: Data Loading
            data_result = execute_ml_stage(
                stage=MLStage.DATA_LOADING, dataset_name=dataset_name
            )

            if data_result["status"] != "completed":
                raise ValueError(f"Data loading failed: {data_result.get('error')}")

            # Create dataset object
            dataset = Dataset(
                name=data_result["dataset_name"],
                features=data_result["features"],
                samples=data_result["samples"],
                target_type=model_type.value.lower(),
                quality_score=data_result["quality_score"],
            )

            # Stage 2: Preprocessing
            preprocess_result = execute_ml_stage(
                stage=MLStage.PREPROCESSING,
                dataset=dataset,
                preprocessing_steps=[
                    "normalize",
                    "feature_selection",
                    "outlier_removal",
                ],
            )

            if preprocess_result["status"] != "completed":
                raise ValueError(
                    f"Preprocessing failed: {preprocess_result.get('error')}"
                )

            # Update dataset with processed features
            dataset.features = preprocess_result["processed_features"]

            # Stage 3: Training
            model_config = self.create_model_config(model_type)
            training_result = execute_ml_stage(
                stage=MLStage.TRAINING, dataset=dataset, model_config=model_config
            )

            if training_result["status"] != "completed":
                raise ValueError(f"Training failed: {training_result.get('error')}")

            # Stage 4: Validation
            validation_result = execute_ml_stage(
                stage=MLStage.VALIDATION,
                model_id=training_result["model_id"],
                training_accuracy=training_result["accuracy"],
            )

            if validation_result["status"] != "completed":
                raise ValueError(f"Validation failed: {validation_result.get('error')}")

            # Stage 5: Prediction (sample)
            prediction_result = execute_ml_stage(
                stage=MLStage.PREDICTION,
                model_id=training_result["model_id"],
                test_samples=5,
            )

            # Pipeline completed
            pipeline_result = {
                "pipeline_id": pipeline_id,
                "dataset_name": dataset_name,
                "model_type": model_type.value,
                "model_id": training_result["model_id"],
                "final_accuracy": validation_result["validation_accuracy"],
                "is_overfitting": validation_result["is_overfitting"],
                "training_time": training_result["training_time"],
                "stages_completed": [
                    "DATA_LOADING",
                    "PREPROCESSING",
                    "TRAINING",
                    "VALIDATION",
                    "PREDICTION",
                ],
                "status": "completed",
            }

            self.event_bus.publish("ml.pipeline.completed", pipeline_result)
            return pipeline_result

        except Exception as e:
            error_result = {
                "pipeline_id": pipeline_id,
                "dataset_name": dataset_name,
                "model_type": model_type.value,
                "status": "failed",
                "error": str(e),
            }
            return error_result

    def run_experiment(
        self, datasets: List[str], model_types: List[ModelType]
    ) -> Dict[str, Any]:
        """Run ML experiment with multiple datasets and models"""

        print(
            f"🧪 Running ML experiment: {len(datasets)} datasets × {len(model_types)} models"
        )

        experiment_results = []

        for dataset_name in datasets:
            for model_type in model_types:
                result = self.run_pipeline(dataset_name, model_type)
                experiment_results.append(result)

                # Brief pause between experiments
                time.sleep(0.1)

        # Analyze experiment results
        successful_runs = [r for r in experiment_results if r["status"] == "completed"]
        best_model = None

        if successful_runs:
            best_model = max(successful_runs, key=lambda x: x["final_accuracy"])

        return {
            "total_experiments": len(experiment_results),
            "successful_runs": len(successful_runs),
            "failed_runs": len(experiment_results) - len(successful_runs),
            "best_model": best_model,
            "all_results": experiment_results,
        }

    def get_metrics(self) -> Dict[str, Any]:
        """Get ML pipeline metrics"""
        return {
            "stage_executions": self.observer.stage_metrics,
            "model_performances": self.observer.model_performances,
            "total_training_time": self.observer.total_training_time,
            "total_errors": self.observer.errors,
            "avg_model_accuracy": (
                sum(self.observer.model_performances.values())
                / len(self.observer.model_performances)
                if self.observer.model_performances
                else 0
            ),
        }

    def shutdown(self):
        """Clean shutdown"""
        self.executor.stop()


def main():
    """Demo the simplified ML pipeline"""
    pipeline = SimpleMLPipeline()

    try:
        # Single pipeline run
        print("🔬 Running single ML pipeline...")
        single_result = pipeline.run_pipeline("iris", ModelType.CLASSIFICATION)

        if single_result["status"] == "completed":
            print(f"✅ Single pipeline: {single_result['final_accuracy']} accuracy")
        else:
            print(f"❌ Single pipeline failed: {single_result['error']}")

        # Experiment with multiple configurations
        print(f"\n🧪 Running ML experiment...")
        datasets = ["iris", "housing", "customers"]
        model_types = [
            ModelType.CLASSIFICATION,
            ModelType.REGRESSION,
            ModelType.CLUSTERING,
        ]

        experiment_result = pipeline.run_experiment(
            datasets[:2], model_types[:2]
        )  # Reduced for demo

        print(f"\n📊 Experiment Results:")
        print(f"  Total experiments: {experiment_result['total_experiments']}")
        print(f"  Successful: {experiment_result['successful_runs']}")
        print(f"  Failed: {experiment_result['failed_runs']}")

        if experiment_result["best_model"]:
            best = experiment_result["best_model"]
            print(
                f"  Best model: {best['model_id']} ({best['final_accuracy']} accuracy)"
            )

        # Show pipeline metrics
        metrics = pipeline.get_metrics()
        print(f"\n📈 Pipeline Metrics:")
        print(f"  Stage executions: {metrics['stage_executions']}")
        print(f"  Models trained: {len(metrics['model_performances'])}")
        print(f"  Average accuracy: {metrics['avg_model_accuracy']:.3f}")
        print(f"  Total training time: {metrics['total_training_time']:.3f}s")

    finally:
        pipeline.shutdown()


if __name__ == "__main__":
    main()
