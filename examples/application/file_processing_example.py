#!/usr/bin/env python3
"""
Uses existing CallPyBack plugins: ThreadExecutor, EventBus, MessageQueue
"""

import json
import random
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List

from callpyback import CallPyBack, on_failure, on_success
from callpyback.observers.base import BaseObserver
from callpyback.plugins.core.message_queue import EventBus, MessageQueue
from callpyback.plugins.executors.thread_executor import ThreadExecutor


class FileOperationType(Enum):
    READ = "READ"
    VALIDATE = "VALIDATE"
    TRANSFORM = "TRANSFORM"
    ARCHIVE = "ARCHIVE"


@dataclass
class FileJob:
    file_path: str
    operation: FileOperationType
    job_id: str
    batch_id: str = ""


class FileProcessingObserver(BaseObserver):
    """Simple file processing observer with metrics"""

    def __init__(self):
        super().__init__(priority=90, name="FileProcessing")
        self.metrics = {
            "processed": 0,
            "errors": 0,
            "total_size": 0,
            "operations": {"READ": 0, "VALIDATE": 0, "TRANSFORM": 0, "ARCHIVE": 0},
        }

    def update(self, context):
        if context.state.name == "COMPLETED":
            if context.result and context.result.value.get("status") == "success":
                self.metrics["processed"] += 1
                self.metrics["total_size"] += context.result.value.get("size_bytes", 0)
                operation = context.arguments.get("job", {})
                if hasattr(operation, "operation"):
                    self.metrics["operations"][operation.operation.value] += 1
            else:
                self.metrics["errors"] += 1


# Global instances
file_observer = FileProcessingObserver()
event_bus = EventBus()
message_queue = MessageQueue()
thread_executor = ThreadExecutor(max_workers=4)


@CallPyBack(
    observers=[
        file_observer,
        on_success(lambda result: event_bus.publish("file.processed", result.value)),
        on_failure(
            lambda result: event_bus.publish(
                "file.error", {"error": str(result.exception)}
            )
        ),
    ]
)
def process_file_job(job: FileJob) -> Dict[str, Any]:
    """Process a single file job with monitoring"""

    file_path = Path(job.file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {job.file_path}")

    # Simulate processing time
    time.sleep(random.uniform(0.01, 0.1))

    # Get file info
    file_size = file_path.stat().st_size

    # Operation-specific processing
    result = {
        "job_id": job.job_id,
        "file_path": str(file_path),
        "operation": job.operation.value,
        "batch_id": job.batch_id,
        "size_bytes": file_size,
        "status": "success",
    }

    if job.operation == FileOperationType.READ:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(1000)  # Read first 1000 chars
        result["lines"] = len(content.splitlines())

    elif job.operation == FileOperationType.VALIDATE:
        result["valid"] = random.choice([True, True, True, False])  # 75% valid

    elif job.operation == FileOperationType.TRANSFORM:
        result["transformed"] = True
        result["new_format"] = file_path.suffix.upper()

    elif job.operation == FileOperationType.ARCHIVE:
        result["archived"] = True
        result["archive_path"] = f"/archive/{file_path.name}"

    return result


class SimpleFileProcessor:
    """Simplified file processor using CallPyBack plugins"""

    def __init__(self):
        self.event_bus = event_bus
        self.message_queue = message_queue
        self.executor = thread_executor

        # Start services
        self.executor.start()
        self.message_queue.start()

        # Setup event handlers
        self.event_bus.subscribe("file.processed", self._on_file_processed)
        self.event_bus.subscribe("file.error", self._on_file_error)

    def _on_file_processed(self, message):
        """Handle successful file processing"""
        payload = message.payload
        print(f"✅ {payload['operation']}: {Path(payload['file_path']).name}")

    def _on_file_error(self, message):
        """Handle file processing errors"""
        print(f"❌ Error: {message.payload['error']}")

    def create_sample_files(self, temp_dir: str = "/tmp/file_test") -> List[str]:
        """Create sample files for testing"""
        Path(temp_dir).mkdir(exist_ok=True)
        files = []

        # Create different file types
        file_types = [
            ("sample.csv", "id,name,value\n1,test,100\n2,demo,200"),
            ("config.json", json.dumps({"enabled": True, "timeout": 30})),
            ("readme.txt", "This is a sample text file\nfor testing purposes."),
            (
                "data.log",
                "2025-01-01 INFO: Sample log entry\n2025-01-01 WARN: Test warning",
            ),
        ]

        for filename, content in file_types:
            file_path = Path(temp_dir) / filename
            with open(file_path, "w") as f:
                f.write(content)
            files.append(str(file_path))

        return files

    def process_files(
        self, file_paths: List[str], operations: List[FileOperationType] = None
    ) -> List[Dict]:
        """Process files using the thread executor"""

        if operations is None:
            operations = [FileOperationType.READ, FileOperationType.VALIDATE]

        # Create jobs
        jobs = []
        batch_id = f"batch_{int(time.time())}"

        for i, file_path in enumerate(file_paths):
            for operation in operations:
                job = FileJob(
                    file_path=file_path,
                    operation=operation,
                    job_id=f"job_{i}_{operation.value}",
                    batch_id=batch_id,
                )
                jobs.append(job)

        print(f"🚀 Processing {len(jobs)} jobs across {len(file_paths)} files")

        # Submit tasks to thread executor
        task_ids = []
        for job in jobs:
            task_id = self.executor.submit(
                process_file_job,
                job,
                priority=1,
            )
            task_ids.append(task_id)

        # Wait for results
        results = []
        for task_id in task_ids:
            try:
                result = self.executor.get_result(task_id, timeout=30)
                results.append(result.result)
            except Exception as e:
                results.append({"error": str(e), "task_id": task_id})

        return results

    def get_metrics(self) -> Dict[str, Any]:
        """Get processing metrics"""
        return {
            "file_metrics": file_observer.metrics,
            "executor_stats": self.executor.get_stats(),
            "queue_stats": self.message_queue.get_stats(),
        }

    def shutdown(self):
        """Clean shutdown"""
        self.executor.stop()
        self.message_queue.stop()


if __name__ == "__main__":
    """Demo the simplified file processor"""
    processor = SimpleFileProcessor()

    try:
        # Create sample files
        sample_files = processor.create_sample_files()
        print(f"📁 Created {len(sample_files)} sample files")

        # Process files
        operations = [
            FileOperationType.READ,
            FileOperationType.VALIDATE,
            FileOperationType.TRANSFORM,
        ]
        results = processor.process_files(sample_files, operations)

        # Show results
        print()
        print("📊 Processing completed. Results:")
        successful = sum(1 for r in results if r.get("status") == "success")
        print(f"  ✅ Successful: {successful}")
        print(f"  ❌ Failed: {len(results) - successful}")

        # Show metrics
        metrics = processor.get_metrics()
        print()
        print("📈 Metrics:")
        print(f"  Files processed: {metrics['file_metrics']['processed']}")
        print(f"  Total size: {metrics['file_metrics']['total_size']} bytes")
        print(f"  Operations: {metrics['file_metrics']['operations']}")

    finally:
        processor.shutdown()
