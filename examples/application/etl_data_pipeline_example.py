#!/usr/bin/env python3
"""
Uses existing CallPyBack plugins: HybridExecutor, EventBus, TopicRegistry
"""

import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from callpyback import CallPyBack, on_call, on_failure, on_success
from callpyback.observers.base import BaseObserver
from callpyback.plugins.core.message_queue import EventBus
from callpyback.plugins.core.topic_registry import TopicRegistry
from callpyback.plugins.executors.hybrid_executor import HybridExecutor


class ETLStage(Enum):
    EXTRACT = "EXTRACT"
    TRANSFORM = "TRANSFORM"
    LOAD = "LOAD"


class DataSource(Enum):
    DATABASE = "DATABASE"
    API = "API"
    FILE = "FILE"


@dataclass
class DataBatch:
    batch_id: str
    source: DataSource
    record_count: int
    size_bytes: int
    metadata: Dict[str, Any]


class ETLMonitor(BaseObserver):
    """Simplified ETL monitoring"""

    def __init__(self):
        super().__init__(priority=95, name="ETLMonitor")
        self.stage_metrics = {"EXTRACT": 0, "TRANSFORM": 0, "LOAD": 0}
        self.total_records = 0
        self.errors = 0

    def update(self, context):
        if context.state.name == "COMPLETED":
            stage = context.arguments.get("stage")
            if stage and hasattr(stage, "value"):
                self.stage_metrics[stage.value] += 1

            if context.result and context.result.value:
                records = context.result.value.get("record_count", 0)
                self.total_records += records
        elif context.state.name == "FAILED":
            self.errors += 1


# Global instances
etl_monitor = ETLMonitor()
event_bus = EventBus()
topic_registry = TopicRegistry()
executor = HybridExecutor(max_threads=3, max_processes=2)


def mock_extract_data(source: DataSource, source_name: str) -> DataBatch:
    """Mock data extraction"""
    time.sleep(random.uniform(0.1, 0.3))  # Simulate extraction time

    record_count = random.randint(100, 1000)
    size_bytes = record_count * random.randint(50, 200)

    return DataBatch(
        batch_id=f"batch_{int(time.time() * 1000) % 10000}",
        source=source,
        record_count=record_count,
        size_bytes=size_bytes,
        metadata={
            "source_name": source_name,
            "extracted_at": time.time(),
            "quality_score": random.uniform(0.8, 1.0),
        },
    )


@CallPyBack(
    observers=[
        etl_monitor,
        on_call(
            lambda context: print(f"🔄 {context.arguments['stage'].value}: Starting...")
        ),
        on_success(
            lambda result: event_bus.publish("etl.stage.completed", result.value)
        ),
        on_failure(
            lambda result: event_bus.publish(
                "etl.stage.failed", {"error": str(result.exception)}
            )
        ),
    ]
)
def execute_etl_stage(
    stage: ETLStage, data_batch: Optional[DataBatch] = None, **kwargs
) -> Dict[str, Any]:
    """Execute ETL stage with monitoring"""

    start_time = time.time()

    try:
        if stage == ETLStage.EXTRACT:
            source_type = kwargs.get("source_type", DataSource.DATABASE)
            source_name = kwargs.get("source_name", "default_db")

            batch = mock_extract_data(source_type, source_name)

            return {
                "stage": stage.value,
                "batch_id": batch.batch_id,
                "record_count": batch.record_count,
                "size_bytes": batch.size_bytes,
                "source": batch.source.value,
                "metadata": batch.metadata,
                "status": "completed",
            }

        elif stage == ETLStage.TRANSFORM:
            if not data_batch:
                raise ValueError("Transform stage requires input data batch")

            # Simulate transformation
            time.sleep(random.uniform(0.05, 0.2))

            # Apply some transformation logic
            transform_rate = kwargs.get("filter_rate", 0.9)
            output_records = int(data_batch.record_count * transform_rate)

            return {
                "stage": stage.value,
                "batch_id": data_batch.batch_id,
                "input_records": data_batch.record_count,
                "record_count": output_records,
                "size_bytes": int(data_batch.size_bytes * transform_rate),
                "transformations_applied": kwargs.get(
                    "transformations", ["cleanse", "validate"]
                ),
                "status": "completed",
            }

        elif stage == ETLStage.LOAD:
            if not data_batch:
                raise ValueError("Load stage requires input data batch")

            # Simulate loading
            time.sleep(random.uniform(0.1, 0.3))

            destination = kwargs.get("destination", "data_warehouse")

            return {
                "stage": stage.value,
                "batch_id": data_batch.batch_id,
                "record_count": data_batch.record_count,
                "destination": destination,
                "load_time": time.time() - start_time,
                "status": "completed",
            }

    except Exception as e:
        return {
            "stage": stage.value,
            "status": "failed",
            "error": str(e),
            "execution_time": time.time() - start_time,
        }


class SimpleETLPipeline:
    """Simplified ETL pipeline using CallPyBack plugins"""

    def __init__(self):
        self.event_bus = event_bus
        self.topic_registry = topic_registry
        self.executor = executor
        self.monitor = etl_monitor

        # Start services
        self.executor.start()

        # Register topics
        self.topic_registry.register_topic(
            "etl.stage.completed", "ETL stage completion events"
        )
        self.topic_registry.register_topic(
            "etl.stage.failed", "ETL stage failure events"
        )
        self.topic_registry.register_topic(
            "etl.pipeline.completed", "Pipeline completion events"
        )

        # Setup event handlers
        self.event_bus.subscribe("etl.stage.completed", self._on_stage_completed)
        self.event_bus.subscribe("etl.stage.failed", self._on_stage_failed)

    def _on_stage_completed(self, message):
        """Handle stage completion"""
        payload = message.payload
        stage = payload.get("stage", "unknown")
        records = payload.get("record_count", 0)
        print(f"✅ {stage} completed: {records} records")

    def _on_stage_failed(self, message):
        """Handle stage failure"""
        error = message.payload.get("error", "Unknown error")
        print(f"❌ Stage failed: {error}")

    def run_pipeline(self, pipeline_config: Dict[str, Any]) -> Dict[str, Any]:
        """Run a complete ETL pipeline"""

        pipeline_name = pipeline_config.get("name", "default_pipeline")
        print(f"🚀 Starting ETL pipeline: {pipeline_name}")

        results = []
        data_batch = None

        try:
            # Extract stage
            extract_config = pipeline_config.get("extract", {})
            extract_result = execute_etl_stage(
                stage=ETLStage.EXTRACT,
                source_type=extract_config.get("source_type", DataSource.DATABASE),
                source_name=extract_config.get("source_name", "default"),
            )
            results.append(extract_result)

            if extract_result["status"] != "completed":
                raise ValueError(f"Extract failed: {extract_result.get('error')}")

            # Create data batch for next stages
            data_batch = DataBatch(
                batch_id=extract_result["batch_id"],
                source=DataSource[extract_result["source"]],
                record_count=extract_result["record_count"],
                size_bytes=extract_result["size_bytes"],
                metadata=extract_result["metadata"],
            )

            # Transform stage
            transform_config = pipeline_config.get("transform", {})
            transform_result = execute_etl_stage(
                stage=ETLStage.TRANSFORM, data_batch=data_batch, **transform_config
            )
            results.append(transform_result)

            if transform_result["status"] != "completed":
                raise ValueError(f"Transform failed: {transform_result.get('error')}")

            # Update data batch
            data_batch.record_count = transform_result["record_count"]
            data_batch.size_bytes = transform_result["size_bytes"]

            # Load stage
            load_config = pipeline_config.get("load", {})
            load_result = execute_etl_stage(
                stage=ETLStage.LOAD, data_batch=data_batch, **load_config
            )
            results.append(load_result)

            if load_result["status"] != "completed":
                raise ValueError(f"Load failed: {load_result.get('error')}")

            # Pipeline completed
            pipeline_result = {
                "pipeline_name": pipeline_name,
                "status": "completed",
                "total_records": data_batch.record_count,
                "stages_completed": [r["stage"] for r in results],
                "results": results,
            }

            self.event_bus.publish("etl.pipeline.completed", pipeline_result)
            return pipeline_result

        except Exception as e:
            error_result = {
                "pipeline_name": pipeline_name,
                "status": "failed",
                "error": str(e),
                "completed_stages": [
                    r["stage"] for r in results if r.get("status") == "completed"
                ],
            }
            return error_result

    def get_metrics(self) -> Dict[str, Any]:
        """Get pipeline metrics"""
        return {
            "stage_executions": self.monitor.stage_metrics,
            "total_records_processed": self.monitor.total_records,
            "total_errors": self.monitor.errors,
            "topic_stats": self.topic_registry.get_stats(),
        }

    def shutdown(self):
        """Clean shutdown"""
        self.executor.stop()


def main():
    """Demo the simplified ETL pipeline"""
    pipeline = SimpleETLPipeline()

    try:
        # Define pipeline configurations
        pipeline_configs = [
            {
                "name": "user_data_pipeline",
                "extract": {
                    "source_type": DataSource.DATABASE,
                    "source_name": "user_db",
                },
                "transform": {
                    "filter_rate": 0.95,
                    "transformations": ["cleanse", "validate", "enrich"],
                },
                "load": {"destination": "data_warehouse"},
            },
            {
                "name": "api_data_pipeline",
                "extract": {
                    "source_type": DataSource.API,
                    "source_name": "external_api",
                },
                "transform": {
                    "filter_rate": 0.8,
                    "transformations": ["normalize", "aggregate"],
                },
                "load": {"destination": "analytics_db"},
            },
        ]

        # Run pipelines
        for config in pipeline_configs:
            result = pipeline.run_pipeline(config)

            if result["status"] == "completed":
                print(
                    f"✅ Pipeline {result['pipeline_name']}: {result['total_records']} records"
                )
            else:
                print(f"❌ Pipeline {result['pipeline_name']}: {result['error']}")

        # Show metrics
        metrics = pipeline.get_metrics()
        print(f"\n📈 Pipeline Metrics:")
        print(f"  Stage executions: {metrics['stage_executions']}")
        print(f"  Total records: {metrics['total_records_processed']}")
        print(f"  Errors: {metrics['total_errors']}")

    finally:
        pipeline.shutdown()


if __name__ == "__main__":
    main()
