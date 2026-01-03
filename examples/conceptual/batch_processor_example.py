#!/usr/bin/env python3
"""
Batch Processor - Conceptual Example
Demonstrates batch processing with message queue events.
"""

import time
from dataclasses import dataclass
from typing import Any, List

from callpyback import (
    ExecutionMode,
    Executor,
    MessageQueue,
    MetricsObserver,
    TimingObserver,
    observe,
)


@dataclass
class BatchItem:
    id: str
    data: Any
    priority: int = 0


@dataclass
class BatchResult:
    id: str
    success: bool
    result: Any = None
    error: str = None
    processing_time: float = 0.0


def main():
    queue = MessageQueue()
    timing = TimingObserver()
    metrics = MetricsObserver()

    results: List[BatchResult] = []

    # Handler for batch item completion
    @queue.on("batch.item.complete")
    def on_item_complete(msg):
        result = msg.payload
        results.append(
            BatchResult(
                id=result["id"],
                success=result["success"],
                result=result.get("result"),
                error=result.get("error"),
                processing_time=result.get("processing_time", 0),
            )
        )

    @queue.on("batch.complete")
    def on_batch_complete(msg):
        print(f"\nBatch complete: {msg.payload['total']} items processed")
        print(f"  Success: {msg.payload['success']}")
        print(f"  Failed: {msg.payload['failed']}")

    # Process function with observers
    @observe(timing, metrics)
    def process_item(item: BatchItem) -> dict:
        start = time.perf_counter()

        # Simulate processing
        time.sleep(0.01)

        # Simulate occasional failures
        if item.id == "item_5":
            raise ValueError(f"Failed to process {item.id}")

        return {
            "id": item.id,
            "success": True,
            "result": f"Processed {item.data}",
            "processing_time": time.perf_counter() - start,
        }

    # Create batch items
    items = [
        BatchItem(id=f"item_{i}", data=f"data_{i}", priority=i % 3) for i in range(10)
    ]

    print("Processing batch...")

    # Process with executor
    with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
        success_count = 0
        fail_count = 0

        for item in items:
            try:
                result = process_item(item)
                queue.publish("batch.item.complete", result)
                success_count += 1
            except Exception as e:
                queue.publish(
                    "batch.item.complete",
                    {"id": item.id, "success": False, "error": str(e)},
                )
                fail_count += 1

        queue.publish(
            "batch.complete",
            {"total": len(items), "success": success_count, "failed": fail_count},
        )

    # Print stats
    print(f"\nTiming stats: {timing.stats}")
    print(f"Metrics stats: {metrics.stats}")


if __name__ == "__main__":
    main()
