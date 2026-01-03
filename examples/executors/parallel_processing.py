#!/usr/bin/env python3
"""
Parallel Processing Examples

This example demonstrates how to use CallPyBack executors for parallel
processing scenarios including batch processing, map-reduce patterns,
and concurrent data processing.
"""

import random
import time
from typing import Any, Dict, List

from callpyback import ExecutionMode, Executor

# ============================================================================
# Helper Functions (defined at module level for ProcessExecutor compatibility)
# ============================================================================


def process_data_chunk(chunk: List[int]) -> Dict[str, Any]:
    """Process a chunk of data."""
    return {
        "sum": sum(chunk),
        "count": len(chunk),
        "min": min(chunk),
        "max": max(chunk),
    }


def compute_statistics(data: List[int]) -> Dict[str, float]:
    """Compute statistics for a dataset."""
    n = len(data)
    mean = sum(data) / n
    variance = sum((x - mean) ** 2 for x in data) / n
    return {
        "mean": mean,
        "variance": variance,
        "std_dev": variance**0.5,
    }


def simulate_api_call(endpoint: str) -> Dict[str, Any]:
    """Simulate an API call with random delay."""
    time.sleep(random.uniform(0.05, 0.15))
    return {
        "endpoint": endpoint,
        "status": 200,
        "data": f"Response from {endpoint}",
    }


def transform_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a single record."""
    return {
        "id": record["id"],
        "name": record["name"].upper(),
        "processed": True,
        "timestamp": time.time(),
    }


# ============================================================================
# Example 1: Batch Processing with ThreadExecutor
# ============================================================================


def batch_processing_example():
    """Demonstrate batch processing pattern."""
    print("\n" + "=" * 60)
    print("Example 1: Batch Processing with Thread Executor")
    print("=" * 60)

    # Simulate batch of records to process
    records = [{"id": i, "name": f"record_{i}"} for i in range(20)]

    with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
        start_time = time.time()

        # Submit all transformations
        task_ids = [executor.submit(transform_record, record) for record in records]

        # Collect results
        transformed = []
        for task_id in task_ids:
            result = executor.result(task_id, timeout=10.0)
            if result.is_success:
                transformed.append(result.value)

        elapsed = time.time() - start_time

        print(f"Processed {len(transformed)} records in {elapsed:.3f}s")
        print(f"Sample result: {transformed[0]}")


# ============================================================================
# Example 2: Map-Reduce Pattern with ProcessExecutor
# ============================================================================


def map_reduce_example():
    """Demonstrate map-reduce pattern for data processing."""
    print("\n" + "=" * 60)
    print("Example 2: Map-Reduce with Process Executor")
    print("=" * 60)

    # Generate large dataset
    data = list(range(1, 100001))

    # Split into chunks
    chunk_size = 10000
    chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]

    print(f"Processing {len(data):,} items in {len(chunks)} chunks...")

    with Executor(mode=ExecutionMode.PROCESS, max_workers=4) as executor:
        start_time = time.time()

        # Map phase: process each chunk in parallel
        task_ids = [executor.submit(process_data_chunk, chunk) for chunk in chunks]

        # Collect intermediate results
        intermediate_results = []
        for task_id in task_ids:
            result = executor.result(task_id, timeout=30.0)
            if result.is_success:
                intermediate_results.append(result.value)

        # Reduce phase: aggregate results
        total_sum = sum(r["sum"] for r in intermediate_results)
        total_count = sum(r["count"] for r in intermediate_results)
        global_min = min(r["min"] for r in intermediate_results)
        global_max = max(r["max"] for r in intermediate_results)

        elapsed = time.time() - start_time

        print(f"\nResults (computed in {elapsed:.3f}s):")
        print(f"  Total sum: {total_sum:,}")
        print(f"  Total count: {total_count:,}")
        print(f"  Global min: {global_min}")
        print(f"  Global max: {global_max}")


# ============================================================================
# Example 3: Concurrent API Calls with ThreadExecutor
# ============================================================================


def concurrent_api_example():
    """Demonstrate concurrent API calls."""
    print("\n" + "=" * 60)
    print("Example 3: Concurrent API Calls")
    print("=" * 60)

    endpoints = [
        "/api/users",
        "/api/posts",
        "/api/comments",
        "/api/albums",
        "/api/photos",
        "/api/todos",
        "/api/settings",
        "/api/notifications",
    ]

    # Sequential (for comparison)
    print("\nSequential execution:")
    start_time = time.time()
    sequential_results = [simulate_api_call(ep) for ep in endpoints]
    sequential_time = time.time() - start_time
    print(f"  Time: {sequential_time:.3f}s")

    # Concurrent
    print("\nConcurrent execution:")
    with Executor(mode=ExecutionMode.THREAD, max_workers=8) as executor:
        start_time = time.time()

        task_ids = [
            executor.submit(simulate_api_call, endpoint) for endpoint in endpoints
        ]

        concurrent_results = []
        for task_id in task_ids:
            result = executor.result(task_id, timeout=10.0)
            if result.is_success:
                concurrent_results.append(result.value)

        concurrent_time = time.time() - start_time
        print(f"  Time: {concurrent_time:.3f}s")

    speedup = sequential_time / concurrent_time
    print(f"\nSpeedup: {speedup:.1f}x faster")


# ============================================================================
# Example 4: Mixed Workload Processing
# ============================================================================


def mixed_workload_example():
    """Demonstrate processing mixed workloads."""
    print("\n" + "=" * 60)
    print("Example 4: Mixed Workload Processing")
    print("=" * 60)

    # Generate multiple datasets
    datasets = [
        list(range(1, 10001)),
        list(range(10001, 20001)),
        list(range(20001, 30001)),
        list(range(30001, 40001)),
    ]

    start_time = time.time()

    # Stage 1: CPU-bound statistics computation (use process executor)
    print("\nStage 1: Computing statistics (CPU-bound, parallel processes)...")
    with Executor(mode=ExecutionMode.PROCESS, max_workers=4) as executor:
        stats_tasks = [executor.submit(compute_statistics, data) for data in datasets]
        statistics = [executor.result(tid, timeout=30.0).value for tid in stats_tasks]

    # Stage 2: I/O-bound API calls (use thread executor)
    print("Stage 2: Storing results (I/O-bound, concurrent threads)...")
    with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
        store_tasks = [
            executor.submit(simulate_api_call, f"/api/store/dataset_{i}")
            for i in range(len(statistics))
        ]
        store_results = [
            executor.result(tid, timeout=10.0).value for tid in store_tasks
        ]

    elapsed = time.time() - start_time

    print(f"\nPipeline completed in {elapsed:.3f}s")
    print(f"Statistics computed: {len(statistics)}")
    print(f"Results stored: {len(store_results)}")


# ============================================================================
# Example 5: Parallel Map Helper
# ============================================================================


def parallel_map_example():
    """Demonstrate parallel map pattern."""
    print("\n" + "=" * 60)
    print("Example 5: Parallel Map Pattern")
    print("=" * 60)

    items = list(range(1, 21))

    def expensive_computation(x):
        """Simulate expensive computation."""
        time.sleep(0.05)
        return x * x

    # Sequential
    print("\nSequential map:")
    start_time = time.time()
    sequential_results = [expensive_computation(x) for x in items]
    sequential_time = time.time() - start_time
    print(f"  Time: {sequential_time:.3f}s")

    # Parallel map using executor
    print("\nParallel map:")
    with Executor(mode=ExecutionMode.THREAD, max_workers=8) as executor:
        start_time = time.time()

        task_ids = [executor.submit(expensive_computation, x) for x in items]
        parallel_results = [executor.result(tid).value for tid in task_ids]

        parallel_time = time.time() - start_time
        print(f"  Time: {parallel_time:.3f}s")

    speedup = sequential_time / parallel_time
    print(f"\nSpeedup: {speedup:.1f}x faster")
    print(f"Results match: {sequential_results == parallel_results}")


# ============================================================================
# Main
# ============================================================================


def main():
    print("=" * 60)
    print("CallPyBack Parallel Processing Examples")
    print("=" * 60)

    batch_processing_example()
    map_reduce_example()
    concurrent_api_example()
    mixed_workload_example()
    parallel_map_example()

    print("\n" + "=" * 60)
    print("All examples completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
