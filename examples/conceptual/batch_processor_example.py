#!/usr/bin/env python3
"""
Simple Batch Processor - Application Example
Demonstrates batch processing with progress tracking and error handling.
"""

import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from callpyback import ExecutionMode, emit_event, on_event, execution_session


@dataclass
class BatchItem:
    id: str
    data: Dict[str, Any]
    priority: int = 1


# Progress tracking
@on_event("batch.started")
def handle_batch_started(message):
    total = message.payload.get("total_items", 0)
    batch_id = message.payload.get("batch_id", "unknown")
    print(f"🚀 Batch {batch_id} started: {total} items")


@on_event("item.processed")
def handle_item_processed(message):
    item_id = message.payload.get("item_id", "unknown")
    processing_time = message.payload.get("processing_time", 0)
    print(f"✅ Processed {item_id} in {processing_time:.2f}s")


@on_event("item.failed")
def handle_item_failed(message):
    item_id = message.payload.get("item_id", "unknown")
    error = message.payload.get("error", "Unknown error")
    print(f"❌ Failed {item_id}: {error}")


@on_event("batch.completed")
def handle_batch_completed(message):
    payload = message.payload
    batch_id = payload.get("batch_id", "unknown")
    success_count = payload.get("successful", 0)
    failed_count = payload.get("failed", 0)
    total_time = payload.get("total_time", 0)

    print(f"🎯 Batch {batch_id} completed:")
    print(f"   ✅ Successful: {success_count}")
    print(f"   ❌ Failed: {failed_count}")
    print(f"   ⏱️ Total time: {total_time:.2f}s")


def process_item(item: BatchItem) -> Dict[str, Any]:
    """Process a single batch item"""
    start_time = time.time()

    try:
        # Simulate processing based on item data
        complexity = item.data.get("complexity", "normal")
        processing_times = {"simple": 0.1, "normal": 0.3, "complex": 0.8}
        base_time = processing_times.get(complexity, 0.3)

        # Add random variation
        sleep_time = base_time + random.uniform(-0.1, 0.2)
        time.sleep(max(0.01, sleep_time))

        # Random failure (10% chance)
        if random.random() < 0.1:
            raise ValueError(f"Processing failed for {item.id}")

        processing_time = time.time() - start_time

        result = {
            "item_id": item.id,
            "status": "success",
            "processing_time": processing_time,
            "output_size": random.randint(100, 1000),
            "complexity": complexity,
        }

        emit_event("item.processed", result)
        return result

    except Exception as e:
        processing_time = time.time() - start_time
        error_result = {
            "item_id": item.id,
            "status": "failed",
            "error": str(e),
            "processing_time": processing_time,
        }

        emit_event("item.failed", error_result)
        return error_result


def create_batch_items(count: int) -> List[BatchItem]:
    """Create sample batch items"""
    items = []
    complexities = ["simple", "normal", "complex"]

    for i in range(count):
        item = BatchItem(
            id=f"item_{i:03d}",
            data={
                "complexity": random.choice(complexities),
                "category": random.choice(["A", "B", "C"]),
                "value": random.randint(1, 1000),
            },
            priority=random.randint(1, 3),
        )
        items.append(item)

    return items


def main():
    """Demo batch processing with the execution manager"""
    print("⚡ Simple Batch Processor")
    print("=" * 40)

    batch_id = f"batch_{int(time.time())}"
    items = create_batch_items(12)

    with execution_session() as manager:
        # Configure for mixed CPU/I/O workload
        manager.configure().max_threads(4).apply()

        # Start batch processing
        start_time = time.time()
        emit_event("batch.started", {"batch_id": batch_id, "total_items": len(items)})

        # Process all items in parallel
        results = manager.map_parallel(process_item, items, mode=ExecutionMode.THREAD)

        # Calculate statistics
        total_time = time.time() - start_time
        successful = [r for r in results if r.get("status") == "success"]
        failed = [r for r in results if r.get("status") == "failed"]

        avg_processing_time = sum(r.get("processing_time", 0) for r in results) / len(
            results
        )
        total_output = sum(r.get("output_size", 0) for r in successful)

        # Emit completion event
        emit_event(
            "batch.completed",
            {
                "batch_id": batch_id,
                "successful": len(successful),
                "failed": len(failed),
                "total_time": total_time,
                "avg_processing_time": avg_processing_time,
                "total_output_size": total_output,
            },
        )

        # Show additional metrics
        metrics = manager.get_metrics()
        print("\n📈 System Metrics:")
        print(f"   Throughput: {len(results)/total_time:.1f} items/sec")
        print(f"   Events published: {metrics['events_published']}")
        print(f"   System health: {manager.health_check()}")


if __name__ == "__main__":
    main()
