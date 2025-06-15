#!/usr/bin/env python3
"""
Multi-Threading Monitoring Example
Demonstrates monitoring concurrent operations with CallPyBack for:
- Thread safety validation
- Concurrency performance tracking
- Race condition detection
- Resource contention monitoring
"""

import random
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List

from callpyback import (
    CallPyBack,
    ExecutionContext,
    ExecutionState,
    on_call,
    on_failure,
    on_success,
)
from callpyback.observers.base import BaseObserver


@dataclass
class WorkItem:
    task_id: str
    data: Any
    priority: int = 1
    worker_id: str = None


class ConcurrencyObserver(BaseObserver):
    """Monitor concurrent execution patterns and thread safety"""

    def __init__(self):
        super().__init__(priority=95, name="ConcurrencyMonitor")
        self.thread_stats = defaultdict(
            lambda: {
                "tasks_completed": 0,
                "total_time": 0,
                "errors": 0,
                "start_time": None,
            }
        )
        self.active_threads = set()
        self.lock = threading.Lock()
        self.concurrent_access_log = deque(maxlen=1000)
        self.resource_contention = defaultdict(int)

    def update(self, context: ExecutionContext) -> None:
        thread_id = threading.current_thread().name

        with self.lock:
            if context.state == ExecutionState.PRE_EXECUTION:
                self.active_threads.add(thread_id)
                if self.thread_stats[thread_id]["start_time"] is None:
                    self.thread_stats[thread_id]["start_time"] = time.time()

                # Log concurrent access
                self.concurrent_access_log.append(
                    {
                        "timestamp": context.timestamp,
                        "thread_id": thread_id,
                        "function": context.function_signature.name,
                        "action": "start",
                        "concurrent_threads": len(self.active_threads),
                    }
                )

                # Detect resource contention
                if len(self.active_threads) > 1:
                    self.resource_contention[context.function_signature.name] += 1

            elif context.state == ExecutionState.COMPLETED:
                self.active_threads.discard(thread_id)

                stats = self.thread_stats[thread_id]
                stats["tasks_completed"] += 1

                if context.result:
                    execution_time = getattr(context.result, "execution_time", 0)
                    stats["total_time"] += execution_time

                    if not context.is_successful:
                        stats["errors"] += 1

                self.concurrent_access_log.append(
                    {
                        "timestamp": context.timestamp,
                        "thread_id": thread_id,
                        "function": context.function_signature.name,
                        "action": "complete",
                        "concurrent_threads": len(self.active_threads),
                        "success": context.is_successful,
                    }
                )

    def get_thread_report(self):
        """Generate thread performance report"""
        with self.lock:
            report = {}
            for thread_id, stats in self.thread_stats.items():
                uptime = time.time() - stats["start_time"] if stats["start_time"] else 0
                avg_time = (
                    stats["total_time"] / stats["tasks_completed"]
                    if stats["tasks_completed"] > 0
                    else 0
                )
                error_rate = (
                    (stats["errors"] / stats["tasks_completed"]) * 100
                    if stats["tasks_completed"] > 0
                    else 0
                )

                report[thread_id] = {
                    "tasks_completed": stats["tasks_completed"],
                    "uptime": f"{uptime:.2f}s",
                    "avg_task_time": f"{avg_time:.3f}s",
                    "error_rate": f"{error_rate:.1f}%",
                    "is_active": thread_id in self.active_threads,
                }
            return report

    def detect_race_conditions(self):
        """Analyze logs for potential race conditions"""
        race_conditions = []

        # Look for overlapping function executions
        function_timeline = defaultdict(list)

        for log_entry in self.concurrent_access_log:
            func_name = log_entry["function"]
            function_timeline[func_name].append(log_entry)

        for func_name, timeline in function_timeline.items():
            # Find overlapping executions
            active_executions = {}

            for entry in sorted(timeline, key=lambda x: x["timestamp"]):
                thread_id = entry["thread_id"]

                if entry["action"] == "start":
                    active_executions[thread_id] = entry
                elif entry["action"] == "complete" and thread_id in active_executions:
                    del active_executions[thread_id]

                # If multiple threads are executing the same function
                if len(active_executions) > 1:
                    race_conditions.append(
                        {
                            "function": func_name,
                            "timestamp": entry["timestamp"],
                            "concurrent_threads": list(active_executions.keys()),
                            "thread_count": len(active_executions),
                        }
                    )

        return race_conditions

    def get_contention_report(self):
        """Report on resource contention"""
        return dict(self.resource_contention)


class PerformanceTracker(BaseObserver):
    """Track performance metrics across threads"""

    def __init__(self):
        super().__init__(priority=85, name="PerformanceTracker")
        self.execution_times = deque(maxlen=500)
        self.throughput_window = deque(maxlen=100)
        self.lock = threading.Lock()

    def update(self, context: ExecutionContext) -> None:
        if context.state == ExecutionState.COMPLETED and context.result:
            execution_time = getattr(context.result, "execution_time", 0)

            with self.lock:
                self.execution_times.append(
                    {
                        "timestamp": context.timestamp,
                        "thread": threading.current_thread().name,
                        "function": context.function_signature.name,
                        "time": execution_time,
                        "success": context.is_successful,
                    }
                )

                # Track throughput (completions per second)
                current_time = time.time()
                self.throughput_window.append(current_time)

    def get_performance_metrics(self):
        """Calculate performance metrics"""
        with self.lock:
            if not self.execution_times:
                return {}

            times = [entry["time"] for entry in self.execution_times]

            # Calculate percentiles
            sorted_times = sorted(times)
            count = len(sorted_times)

            metrics = {
                "total_executions": count,
                "avg_time": sum(times) / count,
                "min_time": min(times),
                "max_time": max(times),
                "p50_time": sorted_times[count // 2] if count > 0 else 0,
                "p95_time": sorted_times[int(count * 0.95)] if count > 0 else 0,
                "p99_time": sorted_times[int(count * 0.99)] if count > 0 else 0,
            }

            # Calculate throughput (tasks per second)
            if len(self.throughput_window) > 1:
                time_span = self.throughput_window[-1] - self.throughput_window[0]
                if time_span > 0:
                    metrics["throughput"] = len(self.throughput_window) / time_span
                else:
                    metrics["throughput"] = 0
            else:
                metrics["throughput"] = 0

            return metrics


# Global observers
concurrency_monitor = ConcurrencyObserver()
performance_tracker = PerformanceTracker()

# Shared resources for simulation
shared_counter = 0
shared_data = {}
counter_lock = threading.Lock()
data_lock = threading.Lock()


@CallPyBack(
    observers=[
        concurrency_monitor,
        performance_tracker,
        on_call(
            lambda context: print(
                f"🔄 [{threading.current_thread().name}] Starting: {context.function_signature.name}"
            )
        ),
    ]
)
def cpu_intensive_task(work_item: WorkItem) -> Dict[str, Any]:
    """Simulate CPU-intensive work"""

    # Simulate varying computational load
    iterations = random.randint(100000, 500000)
    result = 0

    for i in range(iterations):
        result += i**0.5

    return {
        "task_id": work_item.task_id,
        "worker": threading.current_thread().name,
        "result": result,
        "iterations": iterations,
    }


@CallPyBack(observers=[concurrency_monitor, performance_tracker])
def io_simulation_task(work_item: WorkItem) -> Dict[str, Any]:
    """Simulate I/O-bound work with delays"""

    # Simulate network/database call
    io_delay = random.uniform(0.1, 0.5)
    time.sleep(io_delay)

    # Simulate processing response
    processing_time = random.uniform(0.01, 0.05)
    time.sleep(processing_time)

    return {
        "task_id": work_item.task_id,
        "worker": threading.current_thread().name,
        "io_delay": io_delay,
        "total_time": io_delay + processing_time,
    }


@CallPyBack(observers=[concurrency_monitor, performance_tracker])
def shared_resource_task(work_item: WorkItem) -> Dict[str, Any]:
    """Task that accesses shared resources (potential race conditions)"""
    global shared_counter, shared_data

    # Access shared counter (with lock)
    with counter_lock:
        shared_counter += 1
        current_count = shared_counter

    # Simulate some work
    time.sleep(random.uniform(0.01, 0.1))

    # Access shared data structure (potential contention)
    with data_lock:
        key = f"worker_{threading.current_thread().name}"
        if key not in shared_data:
            shared_data[key] = []
        shared_data[key].append(work_item.task_id)

    return {
        "task_id": work_item.task_id,
        "worker": threading.current_thread().name,
        "counter_value": current_count,
        "shared_data_size": len(shared_data.get(key, [])),
    }


@CallPyBack(observers=[concurrency_monitor])
def error_prone_task(work_item: WorkItem) -> Dict[str, Any]:
    """Task that occasionally fails (for error tracking)"""

    # Random failure simulation
    if random.random() < 0.15:  # 15% failure rate
        error_types = [
            ValueError("Invalid data format"),
            ConnectionError("Network connection failed"),
            TimeoutError("Operation timed out"),
            RuntimeError("Processing error"),
        ]
        raise random.choice(error_types)

    time.sleep(random.uniform(0.05, 0.2))

    return {
        "task_id": work_item.task_id,
        "worker": threading.current_thread().name,
        "status": "completed",
    }


def worker_function(task_type: str, work_items: List[WorkItem]) -> List[Dict]:
    """Worker function that processes multiple work items"""
    results = []

    for work_item in work_items:
        work_item.worker_id = threading.current_thread().name

        try:
            if task_type == "cpu":
                result = cpu_intensive_task(work_item)
            elif task_type == "io":
                result = io_simulation_task(work_item)
            elif task_type == "shared":
                result = shared_resource_task(work_item)
            elif task_type == "error_prone":
                result = error_prone_task(work_item)
            else:
                result = {"error": "Unknown task type"}

            results.append(result)

        except Exception as e:
            results.append(
                {
                    "task_id": work_item.task_id,
                    "error": str(e),
                    "worker": threading.current_thread().name,
                }
            )

    return results


def run_concurrent_workload():
    """Simulate realistic concurrent workload"""

    print("🚀 Starting Multi-Threading Simulation")
    print("=" * 50)

    # Create different types of work
    work_types = ["cpu", "io", "shared", "error_prone"]
    all_work_items = []

    for task_type in work_types:
        for i in range(20):  # 20 tasks per type
            work_item = WorkItem(
                task_id=f"{task_type}_{i:03d}",
                data=f"data_for_{task_type}_{i}",
                priority=random.randint(1, 5),
            )
            all_work_items.append((task_type, work_item))

    # Shuffle work for realistic distribution
    random.shuffle(all_work_items)

    # Group work items by type for workers
    work_groups = defaultdict(list)
    for task_type, work_item in all_work_items:
        work_groups[task_type].append(work_item)

    print(
        f"📋 Created {len(all_work_items)} work items across {len(work_types)} task types"
    )

    # Execute with thread pool
    max_workers = 8
    all_results = []

    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="Worker"
    ) as executor:
        # Submit work to different workers
        futures = []

        for task_type, work_items in work_groups.items():
            # Split work items among multiple workers
            chunk_size = max(
                1, len(work_items) // 3
            )  # Distribute across ~3 workers per type

            for i in range(0, len(work_items), chunk_size):
                chunk = work_items[i : i + chunk_size]
                future = executor.submit(worker_function, task_type, chunk)
                futures.append((task_type, future))

        print(f"⚡ Submitted {len(futures)} work batches to {max_workers} workers")

        # Collect results
        completed_batches = 0
        for task_type, future in futures:
            try:
                batch_results = future.result(timeout=30)
                all_results.extend(batch_results)
                completed_batches += 1
                print(
                    f"  ✅ Completed {task_type} batch ({completed_batches}/{len(futures)})"
                )
            except Exception as e:
                print(f"  ❌ Failed {task_type} batch: {e}")

    print(f"\n🏁 Workload completed: {len(all_results)} results collected")

    # Generate comprehensive analysis
    print("\n" + "=" * 60)
    print("📊 CONCURRENCY ANALYSIS REPORT")
    print("=" * 60)

    # Thread performance report
    thread_report = concurrency_monitor.get_thread_report()
    print(f"\n🧵 Thread Performance ({len(thread_report)} threads):")
    for thread_id, stats in thread_report.items():
        print(f"  {thread_id}:")
        print(f"    Tasks: {stats['tasks_completed']}")
        print(f"    Uptime: {stats['uptime']}")
        print(f"    Avg Time: {stats['avg_task_time']}")
        print(f"    Error Rate: {stats['error_rate']}")
        print(f"    Active: {'🟢' if stats['is_active'] else '🔴'}")

    # Performance metrics
    performance_metrics = performance_tracker.get_performance_metrics()
    if performance_metrics:
        print(f"\n⚡ Performance Metrics:")
        print(f"  Total Executions: {performance_metrics['total_executions']}")
        print(f"  Throughput: {performance_metrics['throughput']:.2f} tasks/sec")
        print(f"  Average Time: {performance_metrics['avg_time']:.3f}s")
        print(f"  P50 Time: {performance_metrics['p50_time']:.3f}s")
        print(f"  P95 Time: {performance_metrics['p95_time']:.3f}s")
        print(f"  P99 Time: {performance_metrics['p99_time']:.3f}s")
        print(
            f"  Min/Max: {performance_metrics['min_time']:.3f}s / {performance_metrics['max_time']:.3f}s"
        )

    # Race condition detection
    race_conditions = concurrency_monitor.detect_race_conditions()
    if race_conditions:
        print(f"\n⚠️  Potential Race Conditions Detected: {len(race_conditions)}")
        for race in race_conditions[:5]:  # Show first 5
            print(f"  Function: {race['function']}")
            print(
                f"  Concurrent Threads: {race['thread_count']} ({', '.join(race['concurrent_threads'])})"
            )
    else:
        print(f"\n✅ No race conditions detected")

    # Resource contention
    contention_report = concurrency_monitor.get_contention_report()
    if contention_report:
        print(f"\n🔒 Resource Contention:")
        for function, count in contention_report.items():
            print(f"  {function}: {count} concurrent access events")

    # Shared resource final state
    print(f"\n📊 Shared Resource State:")
    print(f"  Shared Counter: {shared_counter}")
    print(f"  Shared Data Keys: {len(shared_data)}")
    for key, values in list(shared_data.items())[:5]:  # Show first 5
        print(f"    {key}: {len(values)} items")

    # Task completion summary
    successful_tasks = sum(1 for result in all_results if "error" not in result)
    failed_tasks = len(all_results) - successful_tasks

    print(f"\n✅ Task Completion Summary:")
    print(f"  Successful: {successful_tasks}")
    print(f"  Failed: {failed_tasks}")
    print(f"  Success Rate: {(successful_tasks / len(all_results)) * 100:.1f}%")


if __name__ == "__main__":
    run_concurrent_workload()
