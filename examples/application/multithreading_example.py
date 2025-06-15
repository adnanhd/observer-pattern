#!/usr/bin/env python3
"""
Uses enhanced ThreadExecutor with syntactic sugar
"""

import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from enhanced_thread_executor import (
    EnhancedThreadExecutor,
    async_task,
    map_parallel,
    run_parallel,
)

from callpyback import CallPyBack, on_call, on_success


@dataclass
class WorkItem:
    task_id: str
    priority: int
    data: Any


# Shared resources for thread safety testing
shared_counter = 0
shared_data = {}
counter_lock = threading.Lock()
data_lock = threading.Lock()


@async_task(priority=1, timeout=10.0)
def cpu_intensive_task(work_item: WorkItem) -> Dict[str, Any]:
    """CPU-intensive task simulation"""

    # Simulate computation
    result = 0
    for i in range(work_item.data.get("iterations", 1000)):
        result += i * random.random()

    time.sleep(random.uniform(0.05, 0.2))

    return {
        "task_id": work_item.task_id,
        "result": result,
        "thread": threading.current_thread().name,
        "computation_completed": True,
    }


@async_task(priority=2)
def io_simulation_task(work_item: WorkItem) -> Dict[str, Any]:
    """I/O simulation task"""

    # Simulate I/O wait
    io_delay = work_item.data.get("io_delay", random.uniform(0.1, 0.5))
    time.sleep(io_delay)

    return {
        "task_id": work_item.task_id,
        "io_delay": io_delay,
        "thread": threading.current_thread().name,
        "data_fetched": f"data_{work_item.task_id}",
    }


@async_task(priority=3)
def shared_resource_task(work_item: WorkItem) -> Dict[str, Any]:
    """Task that accesses shared resources"""

    global shared_counter, shared_data

    # Thread-safe counter increment
    with counter_lock:
        shared_counter += 1
        current_count = shared_counter

    # Simulate work
    time.sleep(random.uniform(0.01, 0.1))

    # Thread-safe data structure access
    thread_name = threading.current_thread().name
    with data_lock:
        if thread_name not in shared_data:
            shared_data[thread_name] = []
        shared_data[thread_name].append(work_item.task_id)
        data_size = len(shared_data[thread_name])

    return {
        "task_id": work_item.task_id,
        "thread": thread_name,
        "counter_value": current_count,
        "thread_data_size": data_size,
        "status": "completed",
    }


@CallPyBack(
    observers=[
        on_call(
            lambda context: print(
                f"🔄 Processing {context.arguments['work_item'].task_id}"
            )
        ),
        on_success(lambda result: print(f"✅ Completed: {result.value['task_id']}")),
    ]
)
def error_prone_task(work_item: WorkItem) -> Dict[str, Any]:
    """Task that occasionally fails"""

    # Random failure simulation (15% failure rate)
    if random.random() < 0.15:
        error_types = [
            ValueError("Invalid data format"),
            ConnectionError("Network connection failed"),
            TimeoutError("Operation timed out"),
            RuntimeError("Processing error"),
        ]
        raise random.choice(error_types)

    # Simulate processing
    time.sleep(random.uniform(0.05, 0.2))

    return {
        "task_id": work_item.task_id,
        "thread": threading.current_thread().name,
        "processed_successfully": True,
        "processing_time": random.uniform(0.05, 0.2),
    }


class ConcurrencyTester:
    """Test concurrent execution patterns"""

    def __init__(self):
        self.executor = EnhancedThreadExecutor(max_workers=6)
        self.executor.start()

        # Reset shared state
        global shared_counter, shared_data
        shared_counter = 0
        shared_data.clear()

    def create_work_items(self, count: int = 20) -> List[WorkItem]:
        """Create sample work items"""
        items = []

        for i in range(count):
            work_item = WorkItem(
                task_id=f"task_{i:03d}",
                priority=random.randint(1, 3),
                data={
                    "iterations": random.randint(500, 2000),
                    "io_delay": random.uniform(0.05, 0.3),
                    "complexity": random.choice(["low", "medium", "high"]),
                },
            )
            items.append(work_item)

        return items

    def test_parallel_cpu_tasks(self, work_items: List[WorkItem]) -> List[Dict]:
        """Test CPU-intensive tasks in parallel"""
        print("\n🔥 Testing CPU-intensive tasks...")

        # Use map_parallel for easy parallel execution
        results = map_parallel(cpu_intensive_task, work_items)

        print(f"📊 Processed {len(results)} CPU tasks")
        return results

    def test_io_tasks(self, work_items: List[WorkItem]) -> List[Dict]:
        """Test I/O simulation tasks"""
        print("\n📡 Testing I/O tasks...")

        # Submit all tasks and gather results
        async_results = self.executor.map(io_simulation_task, work_items)
        results = self.executor.gather(*async_results)

        avg_delay = sum(r.get("io_delay", 0) for r in results) / len(results)
        print(f"📊 Average I/O delay: {avg_delay:.3f}s")
        return results

    def test_shared_resources(self, work_items: List[WorkItem]) -> List[Dict]:
        """Test shared resource access"""
        print("\n🔒 Testing shared resource access...")

        # Execute tasks that access shared resources
        results = map_parallel(shared_resource_task, work_items[:10])

        print(f"📊 Final counter value: {shared_counter}")
        print(f"📊 Threads with data: {len(shared_data)}")
        return results

    def test_error_handling(self, work_items: List[WorkItem]) -> List[Dict]:
        """Test error handling in concurrent execution"""
        print("\n⚠️  Testing error handling...")

        results = []
        async_results = self.executor.map(error_prone_task, work_items[:8])

        for async_result in async_results:
            try:
                result = async_result.get(timeout=5.0)
                results.append(result)
            except Exception as e:
                results.append({"error": str(e), "status": "failed"})

        successful = sum(1 for r in results if r.get("processed_successfully"))
        failed = len(results) - successful
        print(f"📊 Successful: {successful}, Failed: {failed}")
        return results

    def test_mixed_workload(self, work_items: List[WorkItem]) -> Dict[str, List]:
        """Test mixed workload with different task types"""
        print("\n🔀 Testing mixed workload...")

        # Split work items by task type
        cpu_items = work_items[:5]
        io_items = work_items[5:10]
        shared_items = work_items[10:15]

        # Run different task types in parallel
        mixed_functions = [
            lambda: map_parallel(cpu_intensive_task, cpu_items),
            lambda: map_parallel(io_simulation_task, io_items),
            lambda: map_parallel(shared_resource_task, shared_items),
        ]

        # Execute all workload types concurrently
        workload_results = run_parallel(*mixed_functions)

        return {
            "cpu_results": workload_results[0],
            "io_results": workload_results[1],
            "shared_results": workload_results[2],
        }

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics"""
        return {
            "executor_stats": self.executor.get_stats(),
            "shared_counter": shared_counter,
            "active_threads": len(shared_data),
            "thread_data": {k: len(v) for k, v in shared_data.items()},
        }

    def shutdown(self):
        """Clean shutdown"""
        self.executor.stop()


def main():
    """Demo concurrent execution patterns"""
    print("🚀 Starting Multithreading Simulation with Enhanced Executor")
    print("=" * 60)

    tester = ConcurrencyTester()

    try:
        # Create work items
        work_items = tester.create_work_items(20)
        print(f"📋 Created {len(work_items)} work items")

        # Test different concurrency patterns
        cpu_results = tester.test_parallel_cpu_tasks(work_items[:8])
        io_results = tester.test_io_tasks(work_items[8:16])
        shared_results = tester.test_shared_resources(work_items)
        error_results = tester.test_error_handling(work_items)

        # Test mixed workload
        mixed_results = tester.test_mixed_workload(work_items)

        # Show summary
        print(f"\n📈 Execution Summary:")
        print(f"  CPU tasks: {len(cpu_results)} completed")
        print(f"  I/O tasks: {len(io_results)} completed")
        print(f"  Shared resource tasks: {len(shared_results)} completed")
        print(f"  Error handling tests: {len(error_results)} processed")

        # Show performance metrics
        metrics = tester.get_performance_metrics()
        print(f"\n📊 Performance Metrics:")
        print(f"  Tasks completed: {metrics['executor_stats']['tasks_completed']}")
        print(f"  Tasks failed: {metrics['executor_stats']['tasks_failed']}")
        print(f"  Shared counter: {metrics['shared_counter']}")
        print(f"  Active threads: {metrics['active_threads']}")

    finally:
        tester.shutdown()
        print("\n✅ Multithreading simulation completed!")


if __name__ == "__main__":
    main()
