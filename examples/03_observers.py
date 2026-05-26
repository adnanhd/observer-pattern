"""Observers -- profiling and monitoring task execution.

Meters attach to a task via ``@task(on_execute=[...])`` and accumulate a
running aggregate exposed as ``.stats == {val, avg, sum, count}``. A
``Reporter`` reacts to every AvgMeter's ``"measurement"`` emission via
``@observe(MeterCls, "measurement")``.

Demonstrates: TimingMeter, MetricsMeter, MemoryMeter, a custom AvgMeter, and a
Reporter.
"""

import time
from typing import Any

from eventforge import (
    AvgMeter,
    MemoryMeter,
    MetricsMeter,
    Reporter,
    TimingMeter,
    observe,
    task,
)


def main() -> None:
    # --- TimingMeter: execution time per call -----------------------------
    print("=== TimingMeter ===")
    timing = TimingMeter(threshold=0.1)

    @task(on_execute=[timing])
    def slow_task() -> str:
        time.sleep(0.15)
        return "done"

    slow_task()
    slow_task()
    print(f"timing.stats: {timing.stats}")

    # --- MetricsMeter: pull a number out of each result -------------------
    print("\n=== MetricsMeter ===")
    loss = MetricsMeter("loss", extract=lambda ctx: ctx.result["loss"])

    @task(on_execute=[loss])
    def train_step(x: float) -> dict[str, float]:
        return {"loss": x}

    train_step(0.5)
    train_step(0.3)
    print(f"loss.stats: {loss.stats}")

    # --- MemoryMeter ------------------------------------------------------
    print("\n=== MemoryMeter ===")
    memory = MemoryMeter()

    @task(on_execute=[memory])
    def allocate() -> list[int]:
        return list(range(100_000))

    allocate()
    print(f"memory.stats: {memory.stats}")

    # --- Custom AvgMeter: override measure() ---------------------------------
    print("\n=== Custom AvgMeter ===")

    class RowCountMeter(AvgMeter):
        def measure(self, ctx: Any) -> float:
            return float(len(ctx.result))

    rows = RowCountMeter("rows")

    @task(on_execute=[rows])
    def load_rows(n: int) -> list[int]:
        return list(range(n))

    load_rows(10)
    load_rows(20)
    print(f"rows.stats: {rows.stats}")

    # --- Reporter: react to every TimingMeter's "measurement" emission ----
    print("\n=== Reporter ===")

    class PrintReporter(Reporter):
        @observe(TimingMeter, "measurement")
        def on_timing(self, meter: Any, val: float, ctx: Any) -> None:
            print(f"  [report] {meter.name} measured {val:.4f}s")

    PrintReporter()  # auto-subscribes process-wide to TimingMeter emissions

    reported = TimingMeter(name="reported")

    @task(on_execute=[reported])
    def quick() -> int:
        return 42

    quick()


if __name__ == "__main__":
    main()
