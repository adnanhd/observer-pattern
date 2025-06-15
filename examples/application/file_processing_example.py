#!/usr/bin/env python3
"""
File Processing Monitoring Example
Demonstrates monitoring file processing operations with CallPyBack for:
- Batch file processing
- File system operations monitoring
- Progress tracking
- Error recovery and retry logic
- Processing pipeline monitoring
"""

import os
import random
import shutil
import tempfile
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

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


class FileOperationType(Enum):
    READ = "READ"
    WRITE = "WRITE"
    TRANSFORM = "TRANSFORM"
    VALIDATE = "VALIDATE"
    ARCHIVE = "ARCHIVE"
    DELETE = "DELETE"


class ProcessingStatus(Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


@dataclass
class FileInfo:
    file_path: str
    file_size: int
    file_type: str
    created_at: float
    modified_at: float
    checksum: Optional[str] = None


@dataclass
class ProcessingJob:
    job_id: str
    file_path: str
    operation: FileOperationType
    status: ProcessingStatus = ProcessingStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    processing_options: Dict[str, Any] = None


class FileProcessingObserver(BaseObserver):
    """Monitor file processing operations and performance"""

    def __init__(self):
        super().__init__(priority=90, name="FileProcessing")
        self.operation_stats = defaultdict(
            lambda: {
                "count": 0,
                "total_time": 0,
                "total_bytes": 0,
                "errors": 0,
                "retries": 0,
            }
        )
        self.processing_pipeline = deque(maxlen=500)
        self.error_patterns = defaultdict(int)
        self.throughput_tracker = deque(maxlen=100)
        self.lock = threading.Lock()

    def update(self, context: ExecutionContext) -> None:
        if context.state != ExecutionState.COMPLETED:
            return

        job = context.arguments.get("job")
        if not job:
            return

        with self.lock:
            operation = job.operation.value
            stats = self.operation_stats[operation]
            stats["count"] += 1

            if context.result:
                execution_time = getattr(context.result, "execution_time", 0)
                stats["total_time"] += execution_time

                # Track bytes processed
                result_data = getattr(context.result, "value", {})
                if isinstance(result_data, dict):
                    bytes_processed = result_data.get("bytes_processed", 0)
                    stats["total_bytes"] += bytes_processed

                # Track throughput
                self.throughput_tracker.append(
                    {
                        "timestamp": context.timestamp,
                        "bytes": bytes_processed,
                        "operation": operation,
                    }
                )

                # Track errors and retries
                if not context.is_successful:
                    stats["errors"] += 1
                    error_msg = str(
                        getattr(context.result, "exception", "Unknown error")
                    )
                    error_type = (
                        error_msg.split(":")[0] if ":" in error_msg else error_msg[:30]
                    )
                    self.error_patterns[f"{operation}:{error_type}"] += 1

                if job.retry_count > 0:
                    stats["retries"] += job.retry_count

            # Track processing pipeline
            self.processing_pipeline.append(
                {
                    "timestamp": context.timestamp,
                    "job_id": job.job_id,
                    "operation": operation,
                    "file_path": job.file_path,
                    "status": job.status.value,
                    "retry_count": job.retry_count,
                    "execution_time": (
                        getattr(context.result, "execution_time", 0)
                        if context.result
                        else 0
                    ),
                    "success": context.is_successful,
                }
            )

    def get_processing_report(self):
        """Generate file processing performance report"""
        with self.lock:
            report = {}
            for operation, stats in self.operation_stats.items():
                avg_time = (
                    stats["total_time"] / stats["count"] if stats["count"] > 0 else 0
                )
                error_rate = (
                    (stats["errors"] / stats["count"]) * 100
                    if stats["count"] > 0
                    else 0
                )
                avg_throughput = (
                    stats["total_bytes"] / stats["total_time"]
                    if stats["total_time"] > 0
                    else 0
                )

                report[operation] = {
                    "total_operations": stats["count"],
                    "avg_time": f"{avg_time:.3f}s",
                    "error_rate": f"{error_rate:.1f}%",
                    "total_bytes": self._format_bytes(stats["total_bytes"]),
                    "avg_throughput": f"{self._format_bytes(avg_throughput)}/s",
                    "total_retries": stats["retries"],
                }
            return report

    def get_throughput_analysis(self, window_seconds: int = 60):
        """Calculate throughput over time window"""
        with self.lock:
            current_time = time.time()
            cutoff_time = current_time - window_seconds

            recent_operations = [
                op for op in self.throughput_tracker if op["timestamp"] > cutoff_time
            ]

            if not recent_operations:
                return {}

            total_bytes = sum(op["bytes"] for op in recent_operations)
            time_span = current_time - min(op["timestamp"] for op in recent_operations)

            throughput_by_operation = defaultdict(int)
            for op in recent_operations:
                throughput_by_operation[op["operation"]] += op["bytes"]

            return {
                "window_seconds": window_seconds,
                "total_throughput": f"{self._format_bytes(total_bytes / time_span if time_span > 0 else 0)}/s",
                "operations_per_second": (
                    len(recent_operations) / time_span if time_span > 0 else 0
                ),
                "by_operation": {
                    op: f"{self._format_bytes(bytes_val / time_span if time_span > 0 else 0)}/s"
                    for op, bytes_val in throughput_by_operation.items()
                },
            }

    def get_error_analysis(self):
        """Get error pattern analysis"""
        with self.lock:
            return dict(self.error_patterns)

    def get_recent_jobs(self, limit: int = 20):
        """Get recent processing jobs"""
        with self.lock:
            return list(self.processing_pipeline)[-limit:]

    @staticmethod
    def _format_bytes(bytes_val):
        """Format bytes in human readable format"""
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} TB"


class BatchProcessingObserver(BaseObserver):
    """Monitor batch processing progress and statistics"""

    def __init__(self):
        super().__init__(priority=85, name="BatchProcessing")
        self.batch_stats = {}
        self.active_batches = {}
        self.lock = threading.Lock()

    def update(self, context: ExecutionContext) -> None:
        batch_id = context.arguments.get("batch_id")
        if not batch_id:
            return

        with self.lock:
            if batch_id not in self.batch_stats:
                self.batch_stats[batch_id] = {
                    "total_jobs": 0,
                    "completed_jobs": 0,
                    "failed_jobs": 0,
                    "start_time": context.timestamp,
                    "end_time": None,
                    "total_bytes": 0,
                }

            batch = self.batch_stats[batch_id]

            if context.state == ExecutionState.PRE_EXECUTION:
                batch["total_jobs"] += 1
                self.active_batches[batch_id] = time.time()

            elif context.state == ExecutionState.COMPLETED:
                if context.is_successful:
                    batch["completed_jobs"] += 1

                    # Track bytes processed
                    if context.result:
                        result_data = getattr(context.result, "value", {})
                        if isinstance(result_data, dict):
                            batch["total_bytes"] += result_data.get(
                                "bytes_processed", 0
                            )
                else:
                    batch["failed_jobs"] += 1

                # Check if batch is complete
                if (
                    batch["completed_jobs"] + batch["failed_jobs"]
                    >= batch["total_jobs"]
                ):
                    batch["end_time"] = context.timestamp
                    if batch_id in self.active_batches:
                        del self.active_batches[batch_id]

                    completion_rate = (
                        batch["completed_jobs"] / batch["total_jobs"]
                    ) * 100
                    duration = batch["end_time"] - batch["start_time"]
                    print(
                        f"📋 Batch {batch_id} completed: {completion_rate:.1f}% success rate, {duration:.2f}s duration"
                    )

    def get_batch_progress(self, batch_id: str):
        """Get progress of specific batch"""
        with self.lock:
            if batch_id not in self.batch_stats:
                return None

            batch = self.batch_stats[batch_id]
            processed = batch["completed_jobs"] + batch["failed_jobs"]
            progress = (
                (processed / batch["total_jobs"]) * 100
                if batch["total_jobs"] > 0
                else 0
            )

            return {
                "batch_id": batch_id,
                "progress": f"{progress:.1f}%",
                "completed": batch["completed_jobs"],
                "failed": batch["failed_jobs"],
                "remaining": batch["total_jobs"] - processed,
                "is_active": batch_id in self.active_batches,
                "duration": (
                    time.time() - batch["start_time"]
                    if batch["end_time"] is None
                    else batch["end_time"] - batch["start_time"]
                ),
            }

    def get_all_batches_summary(self):
        """Get summary of all batches"""
        with self.lock:
            summary = {
                "total_batches": len(self.batch_stats),
                "active_batches": len(self.active_batches),
                "completed_batches": sum(
                    1 for b in self.batch_stats.values() if b["end_time"] is not None
                ),
                "batches": {},
            }

            for batch_id, batch in self.batch_stats.items():
                processed = batch["completed_jobs"] + batch["failed_jobs"]
                progress = (
                    (processed / batch["total_jobs"]) * 100
                    if batch["total_jobs"] > 0
                    else 0
                )

                summary["batches"][batch_id] = {
                    "progress": f"{progress:.1f}%",
                    "status": (
                        "active" if batch_id in self.active_batches else "completed"
                    ),
                    "success_rate": (
                        f"{(batch['completed_jobs'] / batch['total_jobs']) * 100:.1f}%"
                        if batch["total_jobs"] > 0
                        else "0%"
                    ),
                }

            return summary


# Set up monitoring
file_monitor = FileProcessingObserver()
batch_monitor = BatchProcessingObserver()

# Error handler for file operations
file_error_handler = DefaultErrorHandler(
    default_return={
        "status": "error",
        "bytes_processed": 0,
        "error": "File operation failed",
    }
)


class MockFileSystem:
    """Mock file system for simulation"""

    def __init__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="callpyback_test_")
        self.files_created = []
        print(f"📁 Created temporary directory: {self.temp_dir}")

        # Create sample files
        self._create_sample_files()

    def _create_sample_files(self):
        """Create sample files for processing"""
        file_types = [
            ("data", ".csv", self._generate_csv_content),
            ("logs", ".log", self._generate_log_content),
            ("config", ".json", self._generate_json_content),
            ("docs", ".txt", self._generate_text_content),
        ]

        for file_type, extension, content_generator in file_types:
            type_dir = Path(self.temp_dir) / file_type
            type_dir.mkdir(exist_ok=True)

            for i in range(random.randint(5, 15)):
                file_path = type_dir / f"{file_type}_{i:03d}{extension}"
                content = content_generator(i)

                with open(file_path, "w") as f:
                    f.write(content)

                self.files_created.append(str(file_path))

    def _generate_csv_content(self, index):
        """Generate sample CSV content"""
        lines = ["id,name,value,timestamp"]
        for i in range(random.randint(50, 200)):
            lines.append(f"{i},item_{i},{random.randint(1, 1000)},{time.time() + i}")
        return "\n".join(lines)

    def _generate_log_content(self, index):
        """Generate sample log content"""
        log_levels = ["INFO", "WARNING", "ERROR", "DEBUG"]
        lines = []
        for i in range(random.randint(100, 500)):
            timestamp = time.time() + i
            level = random.choice(log_levels)
            message = f"Sample log message {i} with some data"
            lines.append(f"{timestamp} [{level}] {message}")
        return "\n".join(lines)

    def _generate_json_content(self, index):
        """Generate sample JSON content"""
        data = {
            "config_id": index,
            "settings": {
                "enabled": random.choice([True, False]),
                "timeout": random.randint(30, 300),
                "retries": random.randint(1, 5),
            },
            "metadata": {
                "created": time.time(),
                "version": f"1.{random.randint(0, 10)}.0",
            },
        }
        import json

        return json.dumps(data, indent=2)

    def _generate_text_content(self, index):
        """Generate sample text content"""
        words = [
            "lorem",
            "ipsum",
            "dolor",
            "sit",
            "amet",
            "consectetur",
            "adipiscing",
            "elit",
        ]
        paragraphs = []
        for _ in range(random.randint(3, 10)):
            paragraph = " ".join(random.choices(words, k=random.randint(20, 50)))
            paragraphs.append(paragraph)
        return "\n\n".join(paragraphs)

    def get_file_info(self, file_path: str) -> FileInfo:
        """Get file information"""
        path = Path(file_path)
        stat = path.stat()

        return FileInfo(
            file_path=file_path,
            file_size=stat.st_size,
            file_type=path.suffix,
            created_at=stat.st_ctime,
            modified_at=stat.st_mtime,
        )

    def cleanup(self):
        """Cleanup temporary files"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            print(f"🗑️  Cleaned up temporary directory: {self.temp_dir}")


# Mock file system instance
mock_fs = MockFileSystem()


@CallPyBack(
    observers=[
        file_monitor,
        batch_monitor,
        on_call(
            lambda context: print(
                f"📄 Processing: {context.arguments['job'].operation.value} - {Path(context.arguments['job'].file_path).name}"
            )
        ),
        on_failure(
            lambda result: print(f"❌ File operation failed: {result.exception}")
        ),
    ],
    error_handler=file_error_handler,
    exception_classes=(IOError, OSError, ValueError),
    variable_names=["processing_stage", "bytes_read", "validation_result"],
)
def process_file(job: ProcessingJob, batch_id: str = None) -> Dict[str, Any]:
    """Process a file according to the job specification"""

    processing_stage = "initializing"
    bytes_read = 0
    validation_result = None

    try:
        file_info = mock_fs.get_file_info(job.file_path)
        processing_stage = "reading"

        # Simulate reading file
        with open(job.file_path, "r") as f:
            content = f.read()
            bytes_read = len(content.encode("utf-8"))

        # Simulate processing time based on file size
        processing_time = min(0.5, bytes_read / 1000000)  # Max 0.5s, 1s per MB
        time.sleep(processing_time)

        processing_stage = "processing"

        # Different operations
        if job.operation == FileOperationType.READ:
            result = {
                "lines_read": len(content.split("\n")),
                "content_preview": (
                    content[:100] + "..." if len(content) > 100 else content
                ),
            }

        elif job.operation == FileOperationType.VALIDATE:
            processing_stage = "validating"
            validation_result = "valid"

            # Simulate validation logic
            if file_info.file_type == ".csv":
                lines = content.split("\n")
                if not lines[0] or "," not in lines[0]:
                    validation_result = "invalid_header"
                    raise ValueError("Invalid CSV header")
            elif file_info.file_type == ".json":
                import json

                try:
                    json.loads(content)
                except json.JSONDecodeError:
                    validation_result = "invalid_json"
                    raise ValueError("Invalid JSON format")

            result = {"validation_status": validation_result}

        elif job.operation == FileOperationType.TRANSFORM:
            processing_stage = "transforming"

            # Simulate transformation (e.g., data cleaning, format conversion)
            if file_info.file_type == ".csv":
                lines = content.split("\n")
                transformed_lines = [
                    line.upper() for line in lines
                ]  # Simple transformation
                result = {
                    "original_lines": len(lines),
                    "transformed_lines": len(transformed_lines),
                    "transformation": "uppercase",
                }
            else:
                result = {
                    "transformation": "generic_processing",
                    "original_size": len(content),
                }

        elif job.operation == FileOperationType.ARCHIVE:
            processing_stage = "archiving"

            # Simulate archiving (copying to archive location)
            archive_dir = Path(mock_fs.temp_dir) / "archive"
            archive_dir.mkdir(exist_ok=True)
            archive_path = archive_dir / Path(job.file_path).name

            shutil.copy2(job.file_path, archive_path)
            result = {
                "archived_to": str(archive_path),
                "archive_size": archive_path.stat().st_size,
            }

        else:
            result = {"operation_completed": True}

        # Simulate occasional errors
        if random.random() < 0.1:  # 10% error rate
            error_types = [
                "Corrupted file data",
                "Insufficient disk space",
                "Permission denied",
                "Network timeout",
                "Processing limit exceeded",
            ]
            raise IOError(random.choice(error_types))

        processing_stage = "completed"
        job.status = ProcessingStatus.COMPLETED

        return {
            "job_id": job.job_id,
            "file_path": job.file_path,
            "operation": job.operation.value,
            "bytes_processed": bytes_read,
            "file_size": file_info.file_size,
            "result": result,
            "status": "success",
        }

    except Exception as e:
        job.status = ProcessingStatus.FAILED
        if job.retry_count < job.max_retries:
            job.retry_count += 1
            job.status = ProcessingStatus.RETRYING
            print(f"🔄 Retrying job {job.job_id} (attempt {job.retry_count + 1})")
            time.sleep(0.1 * job.retry_count)  # Exponential backoff
            return process_file(job, batch_id)
        else:
            raise


def create_processing_jobs(
    file_paths: List[str], operations: List[FileOperationType]
) -> List[ProcessingJob]:
    """Create processing jobs for files"""
    jobs = []

    for i, file_path in enumerate(file_paths):
        operation = random.choice(operations)

        job = ProcessingJob(
            job_id=f"job_{i:04d}",
            file_path=file_path,
            operation=operation,
            max_retries=random.randint(1, 3),
            processing_options={
                "priority": random.randint(1, 5),
                "timeout": random.randint(30, 120),
            },
        )
        jobs.append(job)

    return jobs


def process_batch(batch_id: str, jobs: List[ProcessingJob], max_workers: int = 3):
    """Process a batch of jobs concurrently"""

    print(
        f"\n📦 Starting batch {batch_id} with {len(jobs)} jobs using {max_workers} workers"
    )

    results = []
    failed_jobs = []

    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix=f"Batch-{batch_id}"
    ) as executor:
        # Submit all jobs
        future_to_job = {}
        for job in jobs:
            future = executor.submit(process_file, job, batch_id)
            future_to_job[future] = job

        # Collect results
        for future in as_completed(future_to_job, timeout=60):
            job = future_to_job[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                failed_jobs.append({"job_id": job.job_id, "error": str(e)})

    return results, failed_jobs


def simulate_file_processing_pipeline():
    """Simulate a complete file processing pipeline"""

    print("🚀 Starting File Processing Pipeline Simulation")
    print("=" * 60)

    # Get available files
    available_files = mock_fs.files_created
    print(f"📁 Found {len(available_files)} files to process")

    # Show file distribution by type
    file_types = defaultdict(int)
    for file_path in available_files:
        file_types[Path(file_path).suffix] += 1

    print("📊 File types distribution:")
    for file_type, count in file_types.items():
        print(f"  {file_type}: {count} files")

    # Define processing operations
    operations = [
        FileOperationType.READ,
        FileOperationType.VALIDATE,
        FileOperationType.TRANSFORM,
        FileOperationType.ARCHIVE,
    ]

    # Create processing jobs
    all_jobs = create_processing_jobs(available_files, operations)
    random.shuffle(all_jobs)

    print(f"\n📋 Created {len(all_jobs)} processing jobs")

    # Process in batches
    batch_size = 15
    batch_results = []

    for i in range(0, len(all_jobs), batch_size):
        batch_jobs = all_jobs[i : i + batch_size]
        batch_id = f"batch_{i//batch_size + 1:03d}"

        try:
            results, failed = process_batch(batch_id, batch_jobs, max_workers=4)
            batch_results.append(
                {
                    "batch_id": batch_id,
                    "successful": len(results),
                    "failed": len(failed),
                    "total": len(batch_jobs),
                }
            )

            # Show batch progress
            progress = batch_monitor.get_batch_progress(batch_id)
            if progress:
                print(f"  Batch {batch_id}: {progress['progress']} complete")

        except Exception as e:
            print(f"❌ Batch {batch_id} failed: {e}")
            batch_results.append(
                {
                    "batch_id": batch_id,
                    "successful": 0,
                    "failed": len(batch_jobs),
                    "total": len(batch_jobs),
                }
            )

    print(f"\n🏁 Pipeline completed: {len(batch_results)} batches processed")

    # Generate comprehensive analysis
    print("\n" + "=" * 70)
    print("📊 FILE PROCESSING PIPELINE ANALYSIS")
    print("=" * 70)

    # Processing performance report
    processing_report = file_monitor.get_processing_report()
    print(f"\n🔄 Processing Performance by Operation:")
    for operation, stats in processing_report.items():
        print(f"  {operation}:")
        print(f"    Operations: {stats['total_operations']}")
        print(f"    Avg Time: {stats['avg_time']}")
        print(f"    Error Rate: {stats['error_rate']}")
        print(f"    Total Data: {stats['total_bytes']}")
        print(f"    Throughput: {stats['avg_throughput']}")
        print(f"    Retries: {stats['total_retries']}")

    # Throughput analysis
    throughput_analysis = file_monitor.get_throughput_analysis(
        window_seconds=300
    )  # 5 minutes
    if throughput_analysis:
        print(
            f"\n⚡ Throughput Analysis (last {throughput_analysis['window_seconds']}s):"
        )
        print(f"  Overall: {throughput_analysis['total_throughput']}")
        print(f"  Operations/sec: {throughput_analysis['operations_per_second']:.2f}")
        print(f"  By operation:")
        for operation, throughput in throughput_analysis["by_operation"].items():
            print(f"    {operation}: {throughput}")

    # Batch processing summary
    batch_summary = batch_monitor.get_all_batches_summary()
    print(f"\n📦 Batch Processing Summary:")
    print(f"  Total Batches: {batch_summary['total_batches']}")
    print(f"  Completed Batches: {batch_summary['completed_batches']}")

    # Individual batch results
    print(f"\n📋 Batch Results:")
    total_successful = 0
    total_failed = 0
    for batch_result in batch_results:
        success_rate = (batch_result["successful"] / batch_result["total"]) * 100
        print(
            f"  {batch_result['batch_id']}: {success_rate:.1f}% success ({batch_result['successful']}/{batch_result['total']})"
        )
        total_successful += batch_result["successful"]
        total_failed += batch_result["failed"]

    # Error analysis
    error_analysis = file_monitor.get_error_analysis()
    if error_analysis:
        print(f"\n❌ Error Pattern Analysis:")
        for pattern, count in error_analysis.items():
            print(f"  {pattern}: {count} occurrences")

    # Recent job status
    recent_jobs = file_monitor.get_recent_jobs(limit=10)
    if recent_jobs:
        print(f"\n📄 Recent Job Status (last 10):")
        for job in recent_jobs[-10:]:
            status_icon = "✅" if job["success"] else "❌"
            retry_info = (
                f" (retry {job['retry_count']})" if job["retry_count"] > 0 else ""
            )
            print(
                f"  {status_icon} {job['job_id']}: {job['operation']} - {Path(job['file_path']).name}{retry_info}"
            )

    # Overall statistics
    overall_success_rate = (
        (total_successful / (total_successful + total_failed)) * 100
        if (total_successful + total_failed) > 0
        else 0
    )
    print(f"\n🎯 Overall Pipeline Statistics:")
    print(f"  Total Jobs Processed: {total_successful + total_failed}")
    print(f"  Successful: {total_successful}")
    print(f"  Failed: {total_failed}")
    print(f"  Success Rate: {overall_success_rate:.1f}%")

    # File type processing breakdown
    print(f"\n📂 Processing by File Type:")
    for file_type, count in file_types.items():
        print(f"  {file_type}: {count} files processed")


if __name__ == "__main__":
    try:
        simulate_file_processing_pipeline()
    finally:
        # Cleanup
        mock_fs.cleanup()
