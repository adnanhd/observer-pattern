#!/usr/bin/env python3
"""
ETL/Data Pipeline Monitoring Example
Demonstrates monitoring ETL/data pipelines with CallPyBack for:
- Data extraction performance tracking
- Transformation step monitoring
- Load operation validation
- Data quality checks
- Pipeline dependency management
- Batch processing optimization
"""

import hashlib
import json
import random
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

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


class ETLStage(Enum):
    EXTRACT = "EXTRACT"
    TRANSFORM = "TRANSFORM"
    LOAD = "LOAD"
    VALIDATE = "VALIDATE"
    CLEANUP = "CLEANUP"


class DataSource(Enum):
    DATABASE = "DATABASE"
    API = "API"
    FILE = "FILE"
    STREAM = "STREAM"
    FTP = "FTP"
    S3 = "S3"


class TransformationType(Enum):
    FILTER = "FILTER"
    AGGREGATE = "AGGREGATE"
    JOIN = "JOIN"
    PIVOT = "PIVOT"
    NORMALIZE = "NORMALIZE"
    CLEANSE = "CLEANSE"
    ENRICH = "ENRICH"


@dataclass
class DataBatch:
    batch_id: str
    source: DataSource
    timestamp: float
    record_count: int
    size_bytes: int
    schema_version: str = "1.0"
    checksum: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TransformationStep:
    step_id: str
    transformation_type: TransformationType
    input_count: int
    output_count: int
    processing_time: float
    error_count: int = 0
    validation_passed: bool = True


@dataclass
class PipelineRun:
    run_id: str
    pipeline_name: str
    start_time: float
    end_time: Optional[float] = None
    status: str = "RUNNING"
    stages_completed: List[str] = field(default_factory=list)
    total_records_processed: int = 0
    error_count: int = 0


class ETLPipelineObserver(BaseObserver):
    """Monitor ETL pipeline performance and data flow"""

    def __init__(self):
        super().__init__(priority=95, name="ETLPipeline")
        self.stage_metrics = defaultdict(
            lambda: {
                "executions": 0,
                "total_time": 0,
                "total_records": 0,
                "total_bytes": 0,
                "errors": 0,
                "avg_throughput": 0,
                "execution_history": deque(maxlen=100),
            }
        )
        self.pipeline_runs = {}
        self.data_lineage = defaultdict(list)  # Track data flow
        self.performance_baselines = {}
        self.lock = threading.Lock()

    def update(self, context: ExecutionContext) -> None:
        if context.state != ExecutionState.COMPLETED:
            return

        stage = context.arguments.get("stage")
        if not stage:
            return

        with self.lock:
            stage_name = stage.value if hasattr(stage, "value") else str(stage)
            metrics = self.stage_metrics[stage_name]
            metrics["executions"] += 1

            if context.result:
                execution_time = getattr(context.result, "execution_time", 0)
                metrics["total_time"] += execution_time

                result_data = getattr(context.result, "value", {})
                if isinstance(result_data, dict):

                    # Track data volume
                    record_count = result_data.get("record_count", 0)
                    data_size = result_data.get("data_size", 0)
                    metrics["total_records"] += record_count
                    metrics["total_bytes"] += data_size

                    # Calculate throughput (records per second)
                    if execution_time > 0:
                        throughput = record_count / execution_time
                        metrics["avg_throughput"] = (
                            metrics["avg_throughput"] * (metrics["executions"] - 1)
                            + throughput
                        ) / metrics["executions"]

                    # Track execution details
                    metrics["execution_history"].append(
                        {
                            "timestamp": context.timestamp,
                            "execution_time": execution_time,
                            "record_count": record_count,
                            "data_size": data_size,
                            "success": context.is_successful,
                        }
                    )

                    # Track pipeline run progress
                    run_id = result_data.get("run_id")
                    if run_id:
                        if run_id not in self.pipeline_runs:
                            self.pipeline_runs[run_id] = PipelineRun(
                                run_id=run_id,
                                pipeline_name=result_data.get(
                                    "pipeline_name", "unknown"
                                ),
                                start_time=context.timestamp,
                            )

                        pipeline_run = self.pipeline_runs[run_id]
                        if stage_name not in pipeline_run.stages_completed:
                            pipeline_run.stages_completed.append(stage_name)
                        pipeline_run.total_records_processed += record_count

                        if not context.is_successful:
                            pipeline_run.error_count += 1

                        # Mark run as complete if it's the LOAD stage
                        if stage_name == "LOAD" and context.is_successful:
                            pipeline_run.status = "COMPLETED"
                            pipeline_run.end_time = context.timestamp

                    # Track data lineage
                    source_batch_id = result_data.get("source_batch_id")
                    output_batch_id = result_data.get("batch_id")
                    if source_batch_id and output_batch_id:
                        self.data_lineage[output_batch_id].append(
                            {
                                "source_batch": source_batch_id,
                                "stage": stage_name,
                                "timestamp": context.timestamp,
                                "transformation": result_data.get(
                                    "transformation_type"
                                ),
                            }
                        )

                if not context.is_successful:
                    metrics["errors"] += 1

    def get_pipeline_performance_report(self):
        """Generate ETL pipeline performance report"""
        with self.lock:
            report = {}

            for stage_name, metrics in self.stage_metrics.items():
                if metrics["executions"] == 0:
                    continue

                avg_execution_time = metrics["total_time"] / metrics["executions"]
                error_rate = (metrics["errors"] / metrics["executions"]) * 100
                avg_record_size = (
                    metrics["total_bytes"] / metrics["total_records"]
                    if metrics["total_records"] > 0
                    else 0
                )

                report[stage_name] = {
                    "executions": metrics["executions"],
                    "avg_execution_time": f"{avg_execution_time:.3f}s",
                    "error_rate": f"{error_rate:.1f}%",
                    "total_records": metrics["total_records"],
                    "total_data": self._format_bytes(metrics["total_bytes"]),
                    "avg_throughput": f"{metrics['avg_throughput']:.1f} records/s",
                    "avg_record_size": self._format_bytes(avg_record_size),
                }

            return report

    def get_pipeline_runs_summary(self):
        """Get summary of pipeline runs"""
        with self.lock:
            summary = {
                "total_runs": len(self.pipeline_runs),
                "completed_runs": sum(
                    1
                    for run in self.pipeline_runs.values()
                    if run.status == "COMPLETED"
                ),
                "running_runs": sum(
                    1 for run in self.pipeline_runs.values() if run.status == "RUNNING"
                ),
                "failed_runs": sum(
                    1 for run in self.pipeline_runs.values() if run.status == "FAILED"
                ),
                "runs": {},
            }

            for run_id, run in self.pipeline_runs.items():
                duration = None
                if run.end_time:
                    duration = run.end_time - run.start_time
                elif run.status == "RUNNING":
                    duration = time.time() - run.start_time

                summary["runs"][run_id] = {
                    "pipeline_name": run.pipeline_name,
                    "status": run.status,
                    "duration": f"{duration:.2f}s" if duration else "unknown",
                    "stages_completed": len(run.stages_completed),
                    "records_processed": run.total_records_processed,
                    "error_count": run.error_count,
                }

            return summary

    def get_data_lineage(self, batch_id: str):
        """Get data lineage for a specific batch"""
        with self.lock:
            return self.data_lineage.get(batch_id, [])

    def detect_performance_anomalies(self):
        """Detect performance anomalies based on historical data"""
        with self.lock:
            anomalies = []

            for stage_name, metrics in self.stage_metrics.items():
                if len(metrics["execution_history"]) < 10:
                    continue

                recent_executions = list(metrics["execution_history"])[-10:]
                recent_avg_time = sum(
                    ex["execution_time"] for ex in recent_executions
                ) / len(recent_executions)

                overall_avg_time = metrics["total_time"] / metrics["executions"]

                # Flag if recent performance is 50% worse than average
                if recent_avg_time > overall_avg_time * 1.5:
                    anomalies.append(
                        {
                            "stage": stage_name,
                            "type": "performance_degradation",
                            "recent_avg": recent_avg_time,
                            "overall_avg": overall_avg_time,
                            "degradation_factor": recent_avg_time / overall_avg_time,
                        }
                    )

            return anomalies

    @staticmethod
    def _format_bytes(bytes_val):
        """Format bytes in human readable format"""
        if bytes_val == 0:
            return "0 B"
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"


class DataQualityObserver(BaseObserver):
    """Monitor data quality throughout the pipeline"""

    def __init__(self):
        super().__init__(priority=90, name="DataQuality")
        self.quality_metrics = defaultdict(
            lambda: {
                "null_percentage": [],
                "duplicate_percentage": [],
                "schema_violations": [],
                "data_drift_indicators": [],
                "quality_scores": deque(maxlen=100),
            }
        )
        self.quality_rules = {
            "max_null_percentage": 10.0,
            "max_duplicate_percentage": 5.0,
            "min_quality_score": 0.8,
        }
        self.lock = threading.Lock()

    def update(self, context: ExecutionContext) -> None:
        stage = context.arguments.get("stage")
        if stage != ETLStage.VALIDATE:
            return

        with self.lock:
            if context.result and context.is_successful:
                result_data = getattr(context.result, "value", {})

                batch_id = result_data.get("batch_id", "unknown")
                quality_data = result_data.get("quality_metrics", {})

                metrics = self.quality_metrics[batch_id]

                # Track quality metrics
                if "null_percentage" in quality_data:
                    metrics["null_percentage"].append(quality_data["null_percentage"])

                if "duplicate_percentage" in quality_data:
                    metrics["duplicate_percentage"].append(
                        quality_data["duplicate_percentage"]
                    )

                if "schema_violations" in quality_data:
                    metrics["schema_violations"].append(
                        quality_data["schema_violations"]
                    )

                # Calculate overall quality score
                quality_score = self._calculate_quality_score(quality_data)
                metrics["quality_scores"].append(
                    {
                        "timestamp": context.timestamp,
                        "score": quality_score,
                        "batch_id": batch_id,
                    }
                )

                # Check for quality violations
                violations = self._check_quality_violations(quality_data)
                if violations:
                    print(
                        f"⚠️  Data quality violations detected in batch {batch_id}: {violations}"
                    )

    def _calculate_quality_score(self, quality_data: Dict[str, Any]) -> float:
        """Calculate overall quality score"""
        score = 1.0

        # Penalize high null percentage
        null_pct = quality_data.get("null_percentage", 0)
        score *= max(0, 1 - (null_pct / 100))

        # Penalize duplicates
        dup_pct = quality_data.get("duplicate_percentage", 0)
        score *= max(0, 1 - (dup_pct / 50))  # Less penalty for duplicates

        # Penalize schema violations
        violations = quality_data.get("schema_violations", 0)
        if violations > 0:
            score *= 0.5  # Heavy penalty for schema issues

        return max(0, min(1, score))

    def _check_quality_violations(self, quality_data: Dict[str, Any]) -> List[str]:
        """Check for quality rule violations"""
        violations = []

        null_pct = quality_data.get("null_percentage", 0)
        if null_pct > self.quality_rules["max_null_percentage"]:
            violations.append(f"High null percentage: {null_pct:.1f}%")

        dup_pct = quality_data.get("duplicate_percentage", 0)
        if dup_pct > self.quality_rules["max_duplicate_percentage"]:
            violations.append(f"High duplicate percentage: {dup_pct:.1f}%")

        violations_count = quality_data.get("schema_violations", 0)
        if violations_count > 0:
            violations.append(f"Schema violations: {violations_count}")

        return violations

    def get_quality_report(self):
        """Generate data quality report"""
        with self.lock:
            report = {}

            for batch_id, metrics in self.quality_metrics.items():
                if not metrics["quality_scores"]:
                    continue

                latest_score = metrics["quality_scores"][-1]["score"]
                avg_score = sum(qs["score"] for qs in metrics["quality_scores"]) / len(
                    metrics["quality_scores"]
                )

                avg_null_pct = (
                    sum(metrics["null_percentage"]) / len(metrics["null_percentage"])
                    if metrics["null_percentage"]
                    else 0
                )
                avg_dup_pct = (
                    sum(metrics["duplicate_percentage"])
                    / len(metrics["duplicate_percentage"])
                    if metrics["duplicate_percentage"]
                    else 0
                )
                total_violations = (
                    sum(metrics["schema_violations"])
                    if metrics["schema_violations"]
                    else 0
                )

                report[batch_id] = {
                    "latest_quality_score": f"{latest_score:.3f}",
                    "avg_quality_score": f"{avg_score:.3f}",
                    "avg_null_percentage": f"{avg_null_pct:.1f}%",
                    "avg_duplicate_percentage": f"{avg_dup_pct:.1f}%",
                    "total_schema_violations": total_violations,
                    "quality_trend": self._get_quality_trend(metrics["quality_scores"]),
                }

            return report

    def _get_quality_trend(self, quality_scores: deque) -> str:
        """Determine quality trend"""
        if len(quality_scores) < 3:
            return "insufficient_data"

        recent_scores = [qs["score"] for qs in list(quality_scores)[-3:]]
        if recent_scores[2] > recent_scores[0] * 1.05:
            return "improving"
        elif recent_scores[2] < recent_scores[0] * 0.95:
            return "degrading"
        else:
            return "stable"


# Set up monitoring
etl_pipeline_monitor = ETLPipelineObserver()
data_quality_monitor = DataQualityObserver()

# Error handler for ETL operations
etl_error_handler = DefaultErrorHandler(
    default_return={
        "status": "error",
        "stage_completed": False,
        "error": "ETL operation failed",
    }
)


class MockDataSources:
    """Mock data sources for ETL simulation"""

    def __init__(self):
        self.databases = {
            "customer_db": {
                "tables": ["customers", "orders", "payments"],
                "size": "large",
            },
            "product_db": {
                "tables": ["products", "inventory", "categories"],
                "size": "medium",
            },
            "analytics_db": {
                "tables": ["events", "sessions", "conversions"],
                "size": "large",
            },
        }
        self.api_endpoints = {
            "weather_api": {"rate_limit": 1000, "response_size": "small"},
            "social_media_api": {"rate_limit": 100, "response_size": "large"},
            "financial_api": {"rate_limit": 500, "response_size": "medium"},
        }
        self.file_sources = {
            "daily_logs": {"format": "csv", "size_range": (1000, 10000)},
            "transaction_files": {"format": "json", "size_range": (500, 5000)},
            "sensor_data": {"format": "parquet", "size_range": (10000, 50000)},
        }

    def extract_from_database(
        self, db_name: str, table: str, batch_size: int = 1000
    ) -> DataBatch:
        """Simulate database extraction"""
        if db_name not in self.databases:
            raise ValueError(f"Database {db_name} not found")

        db_info = self.databases[db_name]
        if table not in db_info["tables"]:
            raise ValueError(f"Table {table} not found in {db_name}")

        # Simulate extraction time based on data size
        size_factor = {"small": 0.1, "medium": 0.3, "large": 0.8}.get(
            db_info["size"], 0.3
        )
        extraction_time = random.uniform(0.1, 0.5) * size_factor
        time.sleep(extraction_time)

        # Generate realistic record count based on table type
        base_count = {
            "customers": 50000,
            "orders": 200000,
            "payments": 150000,
            "products": 10000,
            "inventory": 25000,
            "categories": 500,
            "events": 1000000,
            "sessions": 100000,
            "conversions": 50000,
        }.get(table, 10000)

        record_count = min(
            batch_size, random.randint(int(base_count * 0.8), base_count)
        )
        size_bytes = record_count * random.randint(100, 500)  # Rough size estimate

        # Generate checksum
        data_content = f"{db_name}_{table}_{record_count}_{time.time()}"
        checksum = hashlib.md5(data_content.encode()).hexdigest()

        return DataBatch(
            batch_id=f"db_{db_name}_{table}_{int(time.time() * 1000) % 10000}",
            source=DataSource.DATABASE,
            timestamp=time.time(),
            record_count=record_count,
            size_bytes=size_bytes,
            checksum=checksum,
            metadata={
                "database": db_name,
                "table": table,
                "extraction_time": extraction_time,
            },
        )

    def extract_from_api(self, api_name: str, endpoint: str = "data") -> DataBatch:
        """Simulate API extraction"""
        if api_name not in self.api_endpoints:
            raise ValueError(f"API {api_name} not found")

        api_info = self.api_endpoints[api_name]

        # Simulate API call latency
        time.sleep(random.uniform(0.05, 0.3))

        # Simulate rate limiting
        if random.random() < 0.1:  # 10% chance of rate limiting
            raise RuntimeError(f"Rate limit exceeded for {api_name}")

        # Generate data based on API type
        size_factor = {"small": 100, "medium": 1000, "large": 5000}.get(
            api_info["response_size"], 1000
        )
        record_count = random.randint(size_factor // 10, size_factor)
        size_bytes = record_count * random.randint(50, 200)

        return DataBatch(
            batch_id=f"api_{api_name}_{int(time.time() * 1000) % 10000}",
            source=DataSource.API,
            timestamp=time.time(),
            record_count=record_count,
            size_bytes=size_bytes,
            metadata={
                "api": api_name,
                "endpoint": endpoint,
                "rate_limit": api_info["rate_limit"],
            },
        )

    def extract_from_file(self, file_source: str, file_name: str = None) -> DataBatch:
        """Simulate file extraction"""
        if file_source not in self.file_sources:
            raise ValueError(f"File source {file_source} not found")

        file_info = self.file_sources[file_source]

        # Simulate file reading time
        time.sleep(random.uniform(0.02, 0.2))

        # Generate file data
        min_records, max_records = file_info["size_range"]
        record_count = random.randint(min_records, max_records)

        # Size depends on format
        bytes_per_record = {"csv": 150, "json": 300, "parquet": 100}.get(
            file_info["format"], 200
        )
        size_bytes = record_count * bytes_per_record

        return DataBatch(
            batch_id=f"file_{file_source}_{int(time.time() * 1000) % 10000}",
            source=DataSource.FILE,
            timestamp=time.time(),
            record_count=record_count,
            size_bytes=size_bytes,
            metadata={
                "source": file_source,
                "format": file_info["format"],
                "file_name": file_name or f"{file_source}_data",
            },
        )


# Mock data sources instance
data_sources = MockDataSources()


@CallPyBack(
    observers=[
        etl_pipeline_monitor,
        on_call(
            lambda context: print(
                f"🔄 ETL Stage: {context.arguments.get('stage', 'unknown').value if hasattr(context.arguments.get('stage'), 'value') else context.arguments.get('stage', 'unknown')}"
            )
        ),
        on_failure(
            lambda result: print(f"❌ ETL operation failed: {result.exception}")
        ),
    ],
    error_handler=etl_error_handler,
    exception_classes=(ValueError, RuntimeError, ConnectionError, IOError),
    variable_names=[
        "processing_step",
        "record_count",
        "data_quality_check",
        "transformation_config",
    ],
)
def execute_etl_stage(stage: ETLStage, **kwargs) -> Dict[str, Any]:
    """Execute an ETL pipeline stage with monitoring"""

    processing_step = f"initializing_{stage.value.lower()}"
    record_count = 0
    data_quality_check = None
    transformation_config = None

    try:
        if stage == ETLStage.EXTRACT:
            processing_step = "connecting_to_source"

            source_type = kwargs.get("source_type", "database")
            source_name = kwargs.get("source_name", "default")

            # Extract data based on source type
            if source_type == "database":
                table = kwargs.get("table", "default_table")
                batch_size = kwargs.get("batch_size", 1000)
                data_batch = data_sources.extract_from_database(
                    source_name, table, batch_size
                )
            elif source_type == "api":
                endpoint = kwargs.get("endpoint", "data")
                data_batch = data_sources.extract_from_api(source_name, endpoint)
            elif source_type == "file":
                file_name = kwargs.get("file_name")
                data_batch = data_sources.extract_from_file(source_name, file_name)
            else:
                raise ValueError(f"Unsupported source type: {source_type}")

            record_count = data_batch.record_count
            processing_step = "extraction_completed"

            return {
                "stage": stage.value,
                "batch_id": data_batch.batch_id,
                "source_type": source_type,
                "source_name": source_name,
                "record_count": record_count,
                "data_size": data_batch.size_bytes,
                "checksum": data_batch.checksum,
                "metadata": data_batch.metadata,
                "run_id": kwargs.get("run_id"),
                "pipeline_name": kwargs.get("pipeline_name", "unknown"),
                "status": "completed",
            }

        elif stage == ETLStage.TRANSFORM:
            processing_step = "loading_transformation_config"

            input_batch_id = kwargs.get("input_batch_id", "unknown")
            transformation_type = kwargs.get(
                "transformation_type", TransformationType.FILTER
            )
            transformation_config = kwargs.get("transformation_config", {})

            processing_step = "applying_transformations"

            # Simulate different transformation types
            input_records = kwargs.get("input_records", 1000)

            if transformation_type == TransformationType.FILTER:
                # Filtering typically reduces record count
                filter_rate = transformation_config.get("filter_rate", 0.8)
                output_records = int(input_records * filter_rate)
                processing_time = input_records * 0.00001  # Fast operation

            elif transformation_type == TransformationType.AGGREGATE:
                # Aggregation significantly reduces record count
                group_factor = transformation_config.get("group_factor", 10)
                output_records = max(1, input_records // group_factor)
                processing_time = input_records * 0.00005  # Medium operation

            elif transformation_type == TransformationType.JOIN:
                # Joins can increase record count
                join_factor = transformation_config.get("join_factor", 1.2)
                output_records = int(input_records * join_factor)
                processing_time = input_records * 0.0001  # Slower operation

            elif transformation_type == TransformationType.NORMALIZE:
                # Normalization can increase or decrease records
                norm_factor = transformation_config.get("norm_factor", 1.1)
                output_records = int(input_records * norm_factor)
                processing_time = input_records * 0.00003

            else:
                # Default transformation
                output_records = input_records
                processing_time = input_records * 0.00002

            # Simulate processing time
            time.sleep(min(processing_time, 1.0))  # Cap at 1 second for simulation

            record_count = output_records
            processing_step = "transformation_completed"

            # Generate output batch ID
            output_batch_id = f"transform_{transformation_type.value.lower()}_{int(time.time() * 1000) % 10000}"

            return {
                "stage": stage.value,
                "batch_id": output_batch_id,
                "source_batch_id": input_batch_id,
                "transformation_type": transformation_type.value,
                "record_count": output_records,
                "data_size": output_records * random.randint(100, 400),
                "transformation_config": transformation_config,
                "run_id": kwargs.get("run_id"),
                "pipeline_name": kwargs.get("pipeline_name", "unknown"),
                "status": "completed",
            }

        elif stage == ETLStage.VALIDATE:
            processing_step = "running_quality_checks"

            batch_id = kwargs.get("batch_id", "unknown")
            input_records = kwargs.get("input_records", 1000)

            # Simulate data quality checks
            time.sleep(random.uniform(0.1, 0.3))

            # Generate quality metrics
            null_percentage = random.uniform(0, 15)  # 0-15% null values
            duplicate_percentage = random.uniform(0, 8)  # 0-8% duplicates
            schema_violations = (
                random.randint(0, 5) if random.random() < 0.2 else 0
            )  # Occasional violations

            data_quality_check = {
                "null_percentage": null_percentage,
                "duplicate_percentage": duplicate_percentage,
                "schema_violations": schema_violations,
            }

            record_count = input_records
            processing_step = "validation_completed"

            return {
                "stage": stage.value,
                "batch_id": batch_id,
                "record_count": input_records,
                "quality_metrics": data_quality_check,
                "validation_passed": schema_violations == 0 and null_percentage < 10,
                "run_id": kwargs.get("run_id"),
                "pipeline_name": kwargs.get("pipeline_name", "unknown"),
                "status": "completed",
            }

        elif stage == ETLStage.LOAD:
            processing_step = "connecting_to_destination"

            batch_id = kwargs.get("batch_id", "unknown")
            destination = kwargs.get("destination", "data_warehouse")
            input_records = kwargs.get("input_records", 1000)

            processing_step = "loading_data"

            # Simulate loading time based on destination and data size
            load_time_per_record = {
                "data_warehouse": 0.0001,
                "database": 0.00005,
                "file_system": 0.00002,
                "cloud_storage": 0.00008,
            }.get(destination, 0.00005)

            load_time = input_records * load_time_per_record
            time.sleep(min(load_time, 0.8))  # Cap at 0.8 seconds for simulation

            # Simulate occasional load failures
            if random.random() < 0.05:  # 5% failure rate
                raise RuntimeError(f"Load failed: Connection timeout to {destination}")

            record_count = input_records
            processing_step = "load_completed"

            return {
                "stage": stage.value,
                "batch_id": batch_id,
                "destination": destination,
                "record_count": input_records,
                "data_size": input_records * random.randint(150, 500),
                "load_time": load_time,
                "run_id": kwargs.get("run_id"),
                "pipeline_name": kwargs.get("pipeline_name", "unknown"),
                "status": "completed",
            }

        elif stage == ETLStage.CLEANUP:
            processing_step = "cleaning_temporary_files"

            temp_files = kwargs.get("temp_files", [])

            # Simulate cleanup operations
            time.sleep(random.uniform(0.05, 0.2))

            processing_step = "cleanup_completed"

            return {
                "stage": stage.value,
                "files_cleaned": len(temp_files),
                "run_id": kwargs.get("run_id"),
                "pipeline_name": kwargs.get("pipeline_name", "unknown"),
                "status": "completed",
            }

        else:
            raise ValueError(f"Unknown ETL stage: {stage}")

    except Exception as e:
        processing_step = "error_occurred"
        raise


def create_etl_pipeline(
    pipeline_name: str,
    source_configs: List[Dict],
    transformations: List[Dict],
    destination: str,
) -> Dict[str, Any]:
    """Create and execute a complete ETL pipeline"""

    run_id = f"run_{pipeline_name}_{int(time.time() * 1000) % 10000}"
    print(f"🚀 Starting ETL pipeline: {pipeline_name} (Run ID: {run_id})")

    try:
        extracted_batches = []

        # EXTRACT phase
        print(f"📥 Phase 1: Extracting data from {len(source_configs)} sources")
        for i, source_config in enumerate(source_configs):
            try:
                extract_result = execute_etl_stage(
                    ETLStage.EXTRACT,
                    run_id=run_id,
                    pipeline_name=pipeline_name,
                    **source_config,
                )
                extracted_batches.append(extract_result)
                print(
                    f"  ✅ Extracted batch {i+1}: {extract_result['record_count']} records"
                )

            except Exception as e:
                print(f"  ❌ Extraction {i+1} failed: {e}")
                continue

        if not extracted_batches:
            raise RuntimeError("All extractions failed")

        # TRANSFORM phase
        print(f"🔄 Phase 2: Applying {len(transformations)} transformations")
        current_batches = extracted_batches

        for i, transformation in enumerate(transformations):
            transformed_batches = []

            for batch in current_batches:
                try:
                    transform_result = execute_etl_stage(
                        ETLStage.TRANSFORM,
                        input_batch_id=batch["batch_id"],
                        input_records=batch["record_count"],
                        run_id=run_id,
                        pipeline_name=pipeline_name,
                        **transformation,
                    )
                    transformed_batches.append(transform_result)

                except Exception as e:
                    print(
                        f"  ❌ Transformation {i+1} failed for batch {batch['batch_id']}: {e}"
                    )
                    continue

            current_batches = transformed_batches
            total_records = sum(batch["record_count"] for batch in current_batches)
            print(
                f"  ✅ Transformation {i+1} completed: {total_records} records across {len(current_batches)} batches"
            )

        # VALIDATE phase
        print(f"🔍 Phase 3: Validating data quality")
        validated_batches = []

        for batch in current_batches:
            try:
                validate_result = execute_etl_stage(
                    ETLStage.VALIDATE,
                    batch_id=batch["batch_id"],
                    input_records=batch["record_count"],
                    run_id=run_id,
                    pipeline_name=pipeline_name,
                )
                validated_batches.append({**batch, "validation": validate_result})

                if not validate_result["validation_passed"]:
                    print(f"  ⚠️  Quality issues in batch {batch['batch_id']}")

            except Exception as e:
                print(f"  ❌ Validation failed for batch {batch['batch_id']}: {e}")
                validated_batches.append({**batch, "validation": None})

        # LOAD phase
        print(f"📤 Phase 4: Loading data to {destination}")
        loaded_batches = []

        for batch in validated_batches:
            try:
                load_result = execute_etl_stage(
                    ETLStage.LOAD,
                    batch_id=batch["batch_id"],
                    input_records=batch["record_count"],
                    destination=destination,
                    run_id=run_id,
                    pipeline_name=pipeline_name,
                )
                loaded_batches.append(load_result)

            except Exception as e:
                print(f"  ❌ Load failed for batch {batch['batch_id']}: {e}")
                continue

        # CLEANUP phase
        print(f"🧹 Phase 5: Cleanup")
        temp_files = [f"temp_{batch['batch_id']}" for batch in extracted_batches]

        cleanup_result = execute_etl_stage(
            ETLStage.CLEANUP,
            temp_files=temp_files,
            run_id=run_id,
            pipeline_name=pipeline_name,
        )

        total_records_loaded = sum(batch["record_count"] for batch in loaded_batches)

        print(
            f"✅ Pipeline {pipeline_name} completed: {total_records_loaded} records loaded"
        )

        return {
            "run_id": run_id,
            "pipeline_name": pipeline_name,
            "status": "completed",
            "extracted_batches": len(extracted_batches),
            "loaded_batches": len(loaded_batches),
            "total_records_processed": total_records_loaded,
            "validation_results": [
                batch.get("validation") for batch in validated_batches
            ],
        }

    except Exception as e:
        print(f"❌ Pipeline {pipeline_name} failed: {e}")
        return {
            "run_id": run_id,
            "pipeline_name": pipeline_name,
            "status": "failed",
            "error": str(e),
        }


def simulate_etl_pipeline_system():
    """Simulate a complete ETL pipeline system"""

    print("🚀 Starting ETL Pipeline System Simulation")
    print("=" * 60)

    # Define pipeline configurations
    pipeline_configs = [
        {
            "name": "customer_analytics_pipeline",
            "sources": [
                {
                    "source_type": "database",
                    "source_name": "customer_db",
                    "table": "customers",
                    "batch_size": 2000,
                },
                {
                    "source_type": "database",
                    "source_name": "customer_db",
                    "table": "orders",
                    "batch_size": 5000,
                },
                {
                    "source_type": "api",
                    "source_name": "social_media_api",
                    "endpoint": "user_profiles",
                },
            ],
            "transformations": [
                {
                    "transformation_type": TransformationType.FILTER,
                    "transformation_config": {"filter_rate": 0.85},
                },
                {
                    "transformation_type": TransformationType.JOIN,
                    "transformation_config": {"join_factor": 1.3},
                },
                {
                    "transformation_type": TransformationType.AGGREGATE,
                    "transformation_config": {"group_factor": 5},
                },
            ],
            "destination": "data_warehouse",
        },
        {
            "name": "product_inventory_pipeline",
            "sources": [
                {
                    "source_type": "database",
                    "source_name": "product_db",
                    "table": "products",
                    "batch_size": 1000,
                },
                {
                    "source_type": "database",
                    "source_name": "product_db",
                    "table": "inventory",
                    "batch_size": 1500,
                },
                {
                    "source_type": "file",
                    "source_name": "daily_logs",
                    "file_name": "inventory_updates.csv",
                },
            ],
            "transformations": [
                {
                    "transformation_type": TransformationType.CLEANSE,
                    "transformation_config": {},
                },
                {
                    "transformation_type": TransformationType.NORMALIZE,
                    "transformation_config": {"norm_factor": 0.95},
                },
            ],
            "destination": "database",
        },
        {
            "name": "financial_reporting_pipeline",
            "sources": [
                {
                    "source_type": "database",
                    "source_name": "customer_db",
                    "table": "payments",
                    "batch_size": 3000,
                },
                {
                    "source_type": "api",
                    "source_name": "financial_api",
                    "endpoint": "transactions",
                },
                {
                    "source_type": "file",
                    "source_name": "transaction_files",
                    "file_name": "daily_transactions.json",
                },
            ],
            "transformations": [
                {
                    "transformation_type": TransformationType.FILTER,
                    "transformation_config": {"filter_rate": 0.9},
                },
                {
                    "transformation_type": TransformationType.ENRICH,
                    "transformation_config": {},
                },
                {
                    "transformation_type": TransformationType.AGGREGATE,
                    "transformation_config": {"group_factor": 20},
                },
            ],
            "destination": "cloud_storage",
        },
        {
            "name": "iot_sensor_pipeline",
            "sources": [
                {
                    "source_type": "file",
                    "source_name": "sensor_data",
                    "file_name": "sensor_readings.parquet",
                },
                {
                    "source_type": "api",
                    "source_name": "weather_api",
                    "endpoint": "current_conditions",
                },
            ],
            "transformations": [
                {
                    "transformation_type": TransformationType.FILTER,
                    "transformation_config": {"filter_rate": 0.7},
                },
                {
                    "transformation_type": TransformationType.AGGREGATE,
                    "transformation_config": {"group_factor": 100},
                },
            ],
            "destination": "data_warehouse",
        },
    ]

    print(f"📋 Executing {len(pipeline_configs)} ETL pipelines")

    # Execute pipelines
    pipeline_results = []

    # Run some pipelines concurrently
    with ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="ETLPipeline"
    ) as executor:
        futures = []

        for config in pipeline_configs:
            future = executor.submit(
                create_etl_pipeline,
                config["name"],
                config["sources"],
                config["transformations"],
                config["destination"],
            )
            futures.append((config["name"], future))

        # Collect results
        for pipeline_name, future in futures:
            try:
                result = future.result(timeout=60)
                pipeline_results.append(result)

                if result["status"] == "completed":
                    print(
                        f"  ✅ Pipeline {pipeline_name}: {result['total_records_processed']} records processed"
                    )
                else:
                    print(
                        f"  ❌ Pipeline {pipeline_name}: Failed - {result.get('error', 'Unknown error')}"
                    )

            except Exception as e:
                print(f"  ❌ Pipeline {pipeline_name}: Exception - {e}")
                pipeline_results.append(
                    {
                        "pipeline_name": pipeline_name,
                        "status": "failed",
                        "error": str(e),
                    }
                )

    print(f"\n🏁 ETL pipeline system simulation completed")

    # Generate comprehensive analysis
    print("\n" + "=" * 70)
    print("📊 ETL PIPELINE SYSTEM ANALYSIS")
    print("=" * 70)

    # Pipeline performance report
    performance_report = etl_pipeline_monitor.get_pipeline_performance_report()
    print(f"\n🔄 ETL Stage Performance:")
    for stage_name, stats in performance_report.items():
        print(f"  ⚙️  {stage_name}:")
        print(f"    Executions: {stats['executions']}")
        print(f"    Success Rate: {100 - float(stats['error_rate'].rstrip('%')):.1f}%")
        print(f"    Avg Time: {stats['avg_execution_time']}")
        print(f"    Throughput: {stats['avg_throughput']}")
        print(f"    Total Records: {stats['total_records']}")
        print(f"    Total Data: {stats['total_data']}")

    # Pipeline runs summary
    runs_summary = etl_pipeline_monitor.get_pipeline_runs_summary()
    print(f"\n🏃 Pipeline Runs Summary:")
    print(f"  Total Runs: {runs_summary['total_runs']}")
    print(f"  Completed: {runs_summary['completed_runs']}")
    print(f"  Running: {runs_summary['running_runs']}")
    print(f"  Failed: {runs_summary['failed_runs']}")

    print(f"\n  Individual Run Details:")
    for run_id, run_data in runs_summary["runs"].items():
        status_icon = (
            "✅"
            if run_data["status"] == "COMPLETED"
            else "❌" if run_data["status"] == "FAILED" else "🔄"
        )
        print(f"    {status_icon} {run_data['pipeline_name']} ({run_id}):")
        print(f"      Duration: {run_data['duration']}")
        print(f"      Stages: {run_data['stages_completed']}")
        print(f"      Records: {run_data['records_processed']}")
        print(f"      Errors: {run_data['error_count']}")

    # Data quality report
    quality_report = data_quality_monitor.get_quality_report()
    if quality_report:
        print(f"\n📊 Data Quality Analysis:")
        for batch_id, quality_stats in quality_report.items():
            print(f"  📋 Batch {batch_id}:")
            print(
                f"    Quality Score: {quality_stats['latest_quality_score']} (avg: {quality_stats['avg_quality_score']})"
            )
            print(f"    Null Data: {quality_stats['avg_null_percentage']}")
            print(f"    Duplicates: {quality_stats['avg_duplicate_percentage']}")
            print(f"    Schema Violations: {quality_stats['total_schema_violations']}")
            print(f"    Trend: {quality_stats['quality_trend']}")

    # Performance anomaly detection
    anomalies = etl_pipeline_monitor.detect_performance_anomalies()
    if anomalies:
        print(f"\n⚠️  Performance Anomalies Detected:")
        for anomaly in anomalies:
            print(f"  🔍 {anomaly['stage']} - {anomaly['type']}:")
            print(f"    Recent Avg: {anomaly['recent_avg']:.3f}s")
            print(f"    Overall Avg: {anomaly['overall_avg']:.3f}s")
            print(
                f"    Performance Degradation: {anomaly['degradation_factor']:.1f}x slower"
            )
    else:
        print(f"\n✅ No performance anomalies detected")

    # Data lineage examples
    print(f"\n🔗 Data Lineage Examples:")
    for result in pipeline_results[:3]:  # Show lineage for first 3 pipelines
        if result["status"] == "completed":
            pipeline_name = result["pipeline_name"]
            print(f"  📊 {pipeline_name}:")
            print(f"    Extracted → Transformed → Validated → Loaded")
            print(
                f"    Batches: {result['extracted_batches']} → ... → {result['loaded_batches']}"
            )
            print(f"    Total Records: {result['total_records_processed']}")

    # Overall system summary
    successful_pipelines = sum(
        1 for r in pipeline_results if r["status"] == "completed"
    )
    total_records_processed = sum(
        r.get("total_records_processed", 0)
        for r in pipeline_results
        if r["status"] == "completed"
    )

    print(f"\n🎯 System Overview:")
    print(f"  Pipelines Executed: {len(pipeline_results)}")
    print(f"  Successful Pipelines: {successful_pipelines}")
    print(
        f"  Success Rate: {(successful_pipelines / len(pipeline_results)) * 100:.1f}%"
    )
    print(f"  Total Records Processed: {total_records_processed:,}")
    print(
        f"  ETL Stages Executed: {sum(stats['executions'] for stats in performance_report.values())}"
    )

    # Performance insights
    if performance_report:
        fastest_stage = min(
            performance_report.items(),
            key=lambda x: float(x[1]["avg_execution_time"].rstrip("s")),
        )
        slowest_stage = max(
            performance_report.items(),
            key=lambda x: float(x[1]["avg_execution_time"].rstrip("s")),
        )

        print(f"\n💡 Performance Insights:")
        print(
            f"  Fastest Stage: {fastest_stage[0]} ({fastest_stage[1]['avg_execution_time']})"
        )
        print(
            f"  Slowest Stage: {slowest_stage[0]} ({slowest_stage[1]['avg_execution_time']})"
        )

        # Calculate total data processed
        total_data_mb = sum(
            float(stats["total_data"].split()[0])
            for stats in performance_report.values()
            if "MB" in stats["total_data"]
        )
        if total_data_mb > 0:
            print(f"  Total Data Processed: {total_data_mb:.1f} MB")


if __name__ == "__main__":
    simulate_etl_pipeline_system()
