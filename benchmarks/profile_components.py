#!/usr/bin/env python
"""Comprehensive profiling of observer-pattern hot paths (v2).

Eight sections; wall-clock sections go through ``bench.BenchSuite`` so they
collect stats (best / median / p95 / stddev), can dump JSON, and can diff
against a saved baseline. cProfile sections stay standalone.

  1. Eventful.fire subscriber sweep (0, 1, 3, 10, 100 subscribers)
  2. Dispatcher comparison (Broadcast, RoundRobin, Concurrent)
  3. @task lifecycle breakdown (bare vs decorated +/- observers)
  4. WorkQueue enqueue/dequeue
  5. MessageQueue in-memory publish
  6. Meter.attach() cost
  7. Concurrent Eventful.fire (lock contention under N threads)
  8. tracemalloc allocators during sustained task dispatch

Skips TCP and process-mode Executor -- cProfile is not useful there.

Run::

    PYTHONPATH=. python benchmarks/profile_components.py
    PYTHONPATH=. python benchmarks/profile_components.py --output baseline.json
    PYTHONPATH=. python benchmarks/profile_components.py --baseline baseline.json --strict
"""

from __future__ import annotations

import cProfile
import gc
import io
import pstats
import sys
import threading
import time
import tracemalloc
from pathlib import Path

from eventforge import (
    BroadcastDispatcher,
    ConcurrentDispatcher,
    Dispatcher,
    Eventful,
    MessageQueue,
    Meter,
    MetricsMeter,
    RoundRobinDispatcher,
    TimingMeter,
    task,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench import BenchSuite, banner, finalize, parse_args  # noqa: E402


def _print_pstats(pr: cProfile.Profile, top: int = 12) -> None:
    for sort_key, header in (
        ("cumulative", "by cumulative time"),
        ("tottime", "by internal time"),
    ):
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats(sort_key)
        ps.print_stats(top)
        print(f"-- {header} --")
        print(s.getvalue())


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def section_subscriber_sweep(suite: BenchSuite) -> None:
    banner("SECTION 1 -- Eventful.fire vs subscriber count")

    def make_sub(i: int):
        def sub(x: int) -> None:
            _ = x + i

        return sub

    for n_subs in (0, 1, 3, 10, 100):
        ev: Eventful[int] = Eventful()
        for i in range(n_subs):
            ev.subscribe(make_sub(i))
        suite.measure(
            f"Eventful.fire n_subs={n_subs:<3}",
            lambda e=ev: e.fire(42),
            iterations=2000,
            warmup=200,
        )


def section_dispatcher_comparison(suite: BenchSuite) -> None:
    banner("SECTION 2 -- Dispatcher kinds with 10 subscribers")
    from concurrent.futures import ThreadPoolExecutor

    def make_sub(i: int):
        def sub(x: int) -> None:
            _ = x + i

        return sub

    thread_exec = ThreadPoolExecutor(max_workers=2)
    dispatchers: list = [
        ("Broadcast", BroadcastDispatcher()),
        ("RoundRobin", RoundRobinDispatcher()),
        ("Concurrent", ConcurrentDispatcher(executor=thread_exec)),
    ]
    try:
        for label, disp in dispatchers:
            ev: Eventful[int] = Eventful(dispatcher=disp)
            for i in range(10):
                ev.subscribe(make_sub(i))
            suite.measure(
                f"Dispatcher.{label:<11}",
                lambda e=ev: e.fire(42),
                iterations=2000,
                warmup=200,
            )
    finally:
        thread_exec.shutdown(wait=False)


def section_task_lifecycle(suite: BenchSuite) -> None:
    banner("SECTION 3 -- @task() lifecycle breakdown")

    def bare(x: int) -> int:
        return x * 2

    suite.measure("bare function call", lambda: bare(7), iterations=5000, warmup=500)

    decorated = task()(bare)
    suite.measure(
        "@task() no observer", lambda: decorated(7), iterations=5000, warmup=500
    )

    decorated_t = task(on_execute=[TimingMeter()])(bare)
    suite.measure(
        "@task() + TimingMeter", lambda: decorated_t(7), iterations=5000, warmup=500
    )

    decorated_m = task(
        on_execute=[MetricsMeter(name="bench", extract=lambda ctx: 1.0)]
    )(bare)
    suite.measure(
        "@task() + MetricsMeter", lambda: decorated_m(7), iterations=5000, warmup=500
    )

    print()
    print("-- cProfile of @task() no observer, 10k calls --")
    pr = cProfile.Profile()
    pr.enable()
    for i in range(10_000):
        decorated(i)
    pr.disable()
    _print_pstats(pr, top=12)


def section_workqueue(suite: BenchSuite) -> None:
    banner("SECTION 4 -- WorkQueue enqueue + dequeue (50 batches of 100)")
    from eventforge import WorkQueue

    q = WorkQueue()
    TOPIC = "bench.workqueue"

    def enq_then_deq() -> None:
        for i in range(100):
            q.enqueue(TOPIC, i)
        for _ in range(100):
            q.dequeue(TOPIC, timeout=0)

    suite.measure(
        "WorkQueue 100 enq + 100 deq", enq_then_deq, iterations=50, warmup=5, unit="us"
    )


def section_messagequeue(suite: BenchSuite) -> None:
    banner("SECTION 5 -- MessageQueue publish, 5k roundtrips")
    q = MessageQueue()
    received: list = []

    def handler(msg):
        received.append(msg)

    q.subscribe("topic.bench", handler)
    suite.measure(
        "MessageQueue.publish",
        lambda: q.publish("topic.bench", {"x": 1}),
        iterations=5000,
        warmup=500,
    )


def section_meter_attach(suite: BenchSuite) -> None:
    banner("SECTION 6 -- Meter.attach() cost on a deep source class")

    class DeepSource:
        pass

    for i in range(50):
        ev: Eventful[int] = Eventful()
        setattr(DeepSource, f"channel_{i}", ev)
    source = DeepSource()

    class MyMeter(Meter):
        def on_channel_0(self, x: int) -> None:
            pass

        def on_channel_25(self, x: int) -> None:
            pass

    def create_and_attach() -> None:
        m = MyMeter()
        m.attach(source)

    suite.measure(
        "Meter create + attach",
        create_and_attach,
        iterations=500,
        warmup=50,
    )

    print()
    print("-- cProfile of 1000 Meter.attach(source) calls --")
    meters = [MyMeter() for _ in range(1000)]
    pr = cProfile.Profile()
    pr.enable()
    for m in meters:
        m.attach(source)
    pr.disable()
    _print_pstats(pr, top=12)


def section_concurrent_fire(suite: BenchSuite) -> None:
    """Multi-thread Eventful.fire to surface lock contention.

    Each worker fires N times into the SAME shared Eventful with 5
    subscribers. The shared subscriber-list lock inside Eventful.fire is
    what we want to stress. Reported value is the total wall time over
    all threads divided by total fires -- so a result of X us means
    "X us per fire averaged across all threads".
    """
    banner("SECTION 7 -- Eventful.fire under concurrent threads")

    def make_sub(i: int):
        def sub(x: int) -> None:
            _ = x + i

        return sub

    fires_per_thread = 5_000
    for n_threads in (1, 2, 4, 8):
        ev: Eventful[int] = Eventful()
        for i in range(5):
            ev.subscribe(make_sub(i))

        def worker() -> None:
            for j in range(fires_per_thread):
                ev.fire(j)

        def run_concurrent() -> None:
            threads = [threading.Thread(target=worker) for _ in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # Treat one full concurrent run as one "iteration"; we get
        # n_threads * fires_per_thread fires per iter. Time each run, then
        # report normalized per-fire microseconds.
        suite.measure(
            f"concurrent fire threads={n_threads:<2}",
            run_concurrent,
            iterations=5,
            warmup=1,
            unit="ms",
        )
        # Convert the just-collected ms sample to a per-fire us readout.
        s = suite.samples[-1]
        total_fires = n_threads * fires_per_thread
        per_fire_us = (s.best * 1000.0) / total_fires
        print(
            f"   -> {per_fire_us:.3f} us per fire "
            f"(best of 5; {total_fires:,} fires per run)"
        )


def section_tracemalloc() -> None:
    banner("SECTION 8 -- tracemalloc top allocators during 5000 @task() calls")

    def bare(x: int) -> int:
        return x * 2

    decorated = task()(bare)
    for i in range(200):
        decorated(i)
    gc.collect()
    tracemalloc.start(25)
    snap_before = tracemalloc.take_snapshot()
    for i in range(5000):
        decorated(i)
    snap_after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    diff = snap_after.compare_to(snap_before, "lineno")
    print(f"{'rank':>4}  {'size_kb':>10}  {'count':>8}  location")
    print("-" * 78)
    for i, stat in enumerate(diff[:15], 1):
        print(
            f"{i:>4}  {stat.size_diff / 1024:>10.1f}  {stat.count_diff:>8}  "
            f"{stat.traceback}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    args = parse_args()
    suite = BenchSuite(name="observer-pattern.profile_components", cli=args)

    section_subscriber_sweep(suite)
    section_dispatcher_comparison(suite)
    section_task_lifecycle(suite)
    section_workqueue(suite)
    section_messagequeue(suite)
    section_meter_attach(suite)
    section_concurrent_fire(suite)
    section_tracemalloc()

    banner("ASSERT_WITHIN GATES")
    suite.assert_within("Eventful.fire n_subs=3  ", 10.0)  # us, floor ~2.4 us
    suite.assert_within("@task() no observer", 30.0)  # us, floor ~16 us
    suite.assert_within("Meter create + attach", 50.0)  # us, floor ~16 us (post-cache)

    return finalize(suite)


if __name__ == "__main__":
    sys.exit(main())
