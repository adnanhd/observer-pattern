"""Observers - profiling and monitoring task execution.

Demonstrates:
- TimingObserver, MetricsObserver, LoggingObserver
- MemoryObserver, CPUObserver
- Custom observers
- @observe decorator
"""

import time

from callpyback import (
    CPUObserver,
    LoggingObserver,
    MemoryObserver,
    MetricsObserver,
    Observer,
    TimingObserver,
    observe,
)


def main():
    # Timing observer
    print("=== TimingObserver ===")

    timing = TimingObserver(threshold=0.1)

    @observe(timing)
    def slow_task():
        time.sleep(0.15)
        return "done"

    @observe(timing)
    def fast_task():
        return "quick"

    slow_task()
    fast_task()
    fast_task()

    print(f"Stats: {timing.stats}")
    print(f"Timings: {timing.timings}")

    # Metrics observer
    print("\n=== MetricsObserver ===")

    metrics = MetricsObserver()

    @observe(metrics)
    def maybe_fail(should_fail: bool):
        if should_fail:
            raise ValueError("failed")
        return "ok"

    maybe_fail(False)
    maybe_fail(False)
    try:
        maybe_fail(True)
    except ValueError:
        pass

    print(f"Stats: {metrics.stats}")

    # Multiple observers
    print("\n=== Multiple Observers ===")

    timing2 = TimingObserver()
    metrics2 = MetricsObserver()

    @observe(timing2, metrics2)
    def multi_observed():
        time.sleep(0.05)
        return 42

    for _ in range(3):
        multi_observed()

    print(f"Timing: {timing2.stats}")
    print(f"Metrics: {metrics2.stats}")

    # Memory observer
    print("\n=== MemoryObserver ===")

    memory = MemoryObserver()

    @observe(memory)
    def allocate_memory():
        return [i for i in range(100000)]

    allocate_memory()
    print(f"Memory stats: {memory.stats}")

    # Custom observer
    print("\n=== Custom Observer ===")

    class CountingObserver(Observer):
        def __init__(self):
            self.call_count = 0
            self.total_time = 0.0

        def on_start(self, ctx):
            self.call_count += 1

        def on_end(self, ctx):
            self.total_time += ctx.execution_time

        def on_error(self, ctx):
            print(f"Error in {ctx.func_name}: {ctx.error}")

    counter = CountingObserver()

    @observe(counter)
    def counted_task(x):
        time.sleep(0.01)
        return x * 2

    for i in range(5):
        counted_task(i)

    print(f"Calls: {counter.call_count}, Total time: {counter.total_time:.3f}s")


if __name__ == "__main__":
    main()
