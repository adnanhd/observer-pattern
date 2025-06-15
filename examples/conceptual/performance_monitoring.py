#!/usr/bin/env python3
"""
Fixed Performance Monitoring Example
Demonstrates comprehensive performance tracking with proper observer registration.
"""

import random
import time
from collections import defaultdict

from callpyback import CallPyBack
from callpyback.core.state_machine import ExecutionState
from callpyback.observers.base import BaseObserver
from callpyback.observers.builtin import TimingObserver


class AdvancedPerformanceProfiler(BaseObserver):
    """Custom performance profiler with statistical analysis."""

    def __init__(self, percentile_threshold=95):
        super().__init__(priority=100, name="AdvancedProfiler")
        self.execution_times = defaultdict(list)
        self.percentile_threshold = percentile_threshold
        self.slow_executions = []
        self.function_calls = defaultdict(int)

    def update(self, context):
        """Track performance metrics."""
        # Debug print to see what states we're getting
        print(f"DEBUG: Observer called with state: {context.state.name}")

        # Check for both POST_SUCCESS and COMPLETED states
        if context.state in [ExecutionState.POST_SUCCESS, ExecutionState.COMPLETED]:
            if context.result and hasattr(context.result, "execution_time"):
                func_name = context.function_signature.name
                exec_time = context.result.execution_time

                self.execution_times[func_name].append(exec_time)
                self.function_calls[func_name] += 1

                print(f"DEBUG: Recorded {exec_time*1000:.1f}ms for {func_name}")

                # Performance anomaly detection
                if len(self.execution_times[func_name]) >= 5:
                    times = self.execution_times[func_name]
                    threshold = self._calculate_percentile(
                        times, self.percentile_threshold
                    )

                    if exec_time > threshold:
                        alert = {
                            "function": func_name,
                            "time": exec_time,
                            "threshold": threshold,
                            "args": context.arguments,
                            "timestamp": context.timestamp,
                        }
                        self.slow_executions.append(alert)
                        print(
                            f"🐌 PERFORMANCE ALERT: {func_name} took {exec_time*1000:.1f}ms "
                            f"(>{self.percentile_threshold}th percentile: {threshold*1000:.1f}ms)"
                        )
            else:
                print(
                    f"DEBUG: No result or execution_time for state {context.state.name}"
                )

    def _calculate_percentile(self, values, percentile):
        """Calculate percentile value."""
        sorted_values = sorted(values)
        index = int((percentile / 100) * len(sorted_values))
        return sorted_values[min(index, len(sorted_values) - 1)]

    def get_performance_report(self):
        """Generate comprehensive performance report."""
        report = {
            "total_functions": len(self.execution_times),
            "total_executions": sum(
                len(times) for times in self.execution_times.values()
            ),
            "slow_executions": len(self.slow_executions),
            "function_stats": {},
        }

        for func, times in self.execution_times.items():
            if times:
                sorted_times = sorted(times)
                report["function_stats"][func] = {
                    "calls": self.function_calls[func],
                    "min_time": min(times) * 1000,  # Convert to ms
                    "max_time": max(times) * 1000,
                    "avg_time": (sum(times) / len(times)) * 1000,
                    "p50_time": sorted_times[len(sorted_times) // 2] * 1000,
                    "p95_time": self._calculate_percentile(times, 95) * 1000,
                    "p99_time": self._calculate_percentile(times, 99) * 1000,
                }

        return report


# Setup performance monitoring with explicit state registration
profiler = AdvancedPerformanceProfiler(percentile_threshold=90)
timing_observer = TimingObserver(threshold=0.05)  # 50ms threshold

# Create CallPyBack decorator with proper observer registration
performance_decorator = CallPyBack(observers=[profiler, timing_observer])

# IMPORTANT: Manually register profiler for the correct states
performance_decorator.add_observer(
    profiler, states={ExecutionState.POST_SUCCESS, ExecutionState.COMPLETED}
)


@performance_decorator
def cpu_intensive_task(complexity_level, data_size=1000):
    """Simulate CPU-intensive task with variable performance."""
    if complexity_level == "light":
        # Light processing - 10-30ms
        time.sleep(random.uniform(0.01, 0.03))
        result = sum(range(data_size // 100))

    elif complexity_level == "medium":
        # Medium processing - 30-60ms
        time.sleep(random.uniform(0.03, 0.06))
        result = sum(x**2 for x in range(data_size // 50))

    elif complexity_level == "heavy":
        # Heavy processing - 60-120ms
        time.sleep(random.uniform(0.06, 0.12))
        result = sum(x**3 for x in range(data_size // 20))

    elif complexity_level == "variable":
        # Variable processing - 10-150ms (creates outliers)
        time.sleep(random.uniform(0.01, 0.15))
        result = sum(range(random.randint(100, data_size)))

    else:
        # Unknown complexity - minimal processing
        time.sleep(random.uniform(0.005, 0.01))
        result = data_size

    return {"result": result, "complexity": complexity_level, "data_size": data_size}


@performance_decorator
def io_simulation_task(operation_type, delay_factor=1.0):
    """Simulate I/O operations with different characteristics."""
    base_delays = {
        "file_read": 0.02,
        "database_query": 0.04,
        "network_request": 0.08,
        "cache_lookup": 0.005,
    }

    base_delay = base_delays.get(operation_type, 0.01)
    actual_delay = base_delay * delay_factor * random.uniform(0.5, 2.0)

    time.sleep(actual_delay)

    return {
        "operation": operation_type,
        "delay_factor": delay_factor,
        "simulated_delay": actual_delay,
    }


@performance_decorator
def memory_intensive_task(memory_size="small"):
    """Simulate memory-intensive operations."""
    sizes = {"small": 1000, "medium": 10000, "large": 100000}

    size = sizes.get(memory_size, 1000)

    # Simulate memory allocation and processing
    start_time = time.time()
    data = list(range(size))
    processed = [x * 2 for x in data if x % 2 == 0]
    processing_time = time.time() - start_time

    # Add artificial delay to make timing visible
    time.sleep(random.uniform(0.01, 0.05))

    return {
        "memory_size": memory_size,
        "items_processed": len(processed),
        "processing_time": processing_time,
    }


if __name__ == "__main__":
    print("=== Fixed Performance Monitoring Example ===")

    # Performance test scenarios
    print("Running performance tests...")

    # Test 1: CPU-intensive tasks with different complexity levels
    print("1. CPU-intensive task performance:")
    cpu_test_scenarios = [
        ("light", 500),
        ("light", 1000),
        ("medium", 500),
        ("medium", 1000),
        ("heavy", 500),
    ]

    for complexity, size in cpu_test_scenarios:
        result = cpu_intensive_task(complexity, size)
        print(f"  {complexity} ({size}): processed")

    # Test 2: I/O simulation with different delay factors
    print("\n2. I/O operation performance:")
    io_test_scenarios = [
        ("cache_lookup", 1.0),
        ("file_read", 1.0),
        ("database_query", 1.0),
        ("network_request", 1.0),
    ]

    for operation, delay_factor in io_test_scenarios:
        result = io_simulation_task(operation, delay_factor)
        print(f"  {operation} (x{delay_factor}): completed")

    # Test 3: Memory-intensive tasks
    print("\n3. Memory-intensive task performance:")
    memory_test_scenarios = ["small", "medium", "large"]

    for memory_size in memory_test_scenarios:
        result = memory_intensive_task(memory_size)
        print(f"  {memory_size}: {result['items_processed']} items processed")

    # Generate comprehensive performance report
    print("\n" + "=" * 60)
    print("PERFORMANCE ANALYSIS REPORT")
    print("=" * 60)

    performance_report = profiler.get_performance_report()

    print("Overall Statistics:")
    print(f"  Total functions monitored: {performance_report['total_functions']}")
    print(f"  Total executions: {performance_report['total_executions']}")
    print(f"  Performance alerts: {performance_report['slow_executions']}")

    if performance_report["function_stats"]:
        print("\nFunction Performance Breakdown:")
        for func_name, stats in performance_report["function_stats"].items():
            print(f"\n  {func_name}:")
            print(f"    Calls: {stats['calls']}")
            print(f"    Min time: {stats['min_time']:.1f}ms")
            print(f"    Avg time: {stats['avg_time']:.1f}ms")
            print(f"    Max time: {stats['max_time']:.1f}ms")
            print(f"    P50 time: {stats['p50_time']:.1f}ms")
            print(f"    P95 time: {stats['p95_time']:.1f}ms")
            print(f"    P99 time: {stats['p99_time']:.1f}ms")

        # Performance insights
        print("\nPerformance Insights:")

        # Find slowest function
        slowest_func = max(
            performance_report["function_stats"].items(), key=lambda x: x[1]["avg_time"]
        )
        print(
            f"  Slowest function: {slowest_func[0]} "
            f"(avg: {slowest_func[1]['avg_time']:.1f}ms)"
        )

        # Find most variable function
        most_variable = None
        highest_variability = 0

        for func_name, stats in performance_report["function_stats"].items():
            variability = stats["max_time"] - stats["min_time"]
            if variability > highest_variability:
                highest_variability = variability
                most_variable = func_name

        if most_variable:
            print(
                f"  Most variable function: {most_variable} "
                f"(range: {highest_variability:.1f}ms)"
            )

        # Calculate overall success rate
        total_alerts = performance_report["slow_executions"]
        total_executions = performance_report["total_executions"]
        if total_executions > 0:
            performance_score = (
                (total_executions - total_alerts) / total_executions
            ) * 100
            print(
                f"  Performance score: {performance_score:.1f}% "
                f"({total_executions - total_alerts}/{total_executions} within thresholds)"
            )
    else:
        print("\nNo performance data collected. Check observer registration.")

    # Debug information
    print("\nDebug Info:")
    print(f"  Profiler execution_times: {dict(profiler.execution_times)}")
    print(f"  Profiler function_calls: {dict(profiler.function_calls)}")
