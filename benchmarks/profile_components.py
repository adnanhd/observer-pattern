#!/usr/bin/env python
"""Comprehensive profiling of observer-pattern hot paths.

Covers seven angles:

  1. Eventful.fire subscriber sweep (0, 1, 3, 10, 100 subscribers)
  2. Dispatcher comparison (Broadcast, RoundRobin, Concurrent)
  3. @task lifecycle breakdown -- UUID generation, _execute, fire overhead
  4. WorkQueue enqueue/dequeue
  5. MessageQueue in-memory roundtrip
  6. Meter attach cost (dir-walk over source channels)
  7. tracemalloc allocators during sustained task dispatch

Skips TCP and process-mode Executor -- cProfile is not useful for socket I/O
or fork overhead.

Run::

    PYTHONPATH=. python benchmarks/profile_components.py
"""

from __future__ import annotations

import cProfile
import gc
import io
import pstats
import time
import tracemalloc
from typing import Any

from callpyback import (
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def banner(text: str) -> None:
    print()
    print("#" * 72)
    print(f"# {text}")
    print("#" * 72)


def print_pstats(pr: cProfile.Profile, top: int = 12) -> None:
    for sort_key, header in (
        ("cumulative", "by cumulative time"),
        ("tottime", "by internal time"),
    ):
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats(sort_key)
        ps.print_stats(top)
        print(f"-- {header} --")
        print(s.getvalue())


def time_us(fn, iterations: int, warmup: int = 50) -> tuple[float, float]:
    """Returns (best_us_per_call, mean_us_per_call)."""
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(iterations):
        gc.collect()
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1_000_000.0)
    return min(samples), sum(samples) / len(samples)


# ---------------------------------------------------------------------------
# Section 1: Eventful.fire subscriber sweep
# ---------------------------------------------------------------------------


def section_subscriber_sweep() -> None:
    banner("SECTION 1 -- Eventful.fire vs subscriber count (microseconds per fire)")

    def make_sub(i: int):
        def sub(x: int) -> None:
            _ = x + i

        return sub

    print(f"{'subs':>6} {'best_us':>10} {'mean_us':>10}")
    print("-" * 30)
    for n_subs in (0, 1, 3, 10, 100):
        ev: Eventful[int] = Eventful()
        for i in range(n_subs):
            ev.subscribe(make_sub(i))
        best, mean = time_us(lambda e=ev: e.fire(42), iterations=2000, warmup=200)
        print(f"{n_subs:>6} {best:>10.3f} {mean:>10.3f}")


# ---------------------------------------------------------------------------
# Section 2: Dispatcher comparison
# ---------------------------------------------------------------------------


def section_dispatcher_comparison() -> None:
    banner("SECTION 2 -- Dispatcher kinds with 10 subscribers, 2000 dispatches each")

    def make_sub(i: int):
        def sub(x: int) -> None:
            _ = x + i

        return sub

    from concurrent.futures import ThreadPoolExecutor

    thread_exec = ThreadPoolExecutor(max_workers=2)
    # LeastLoaded skipped: it requires Node subscribers with a .load() method,
    # incompatible with the plain-callable subscribers used elsewhere in this script.
    dispatchers: list[tuple[str, Dispatcher]] = [
        ("Broadcast", BroadcastDispatcher()),
        ("RoundRobin", RoundRobinDispatcher()),
        ("Concurrent", ConcurrentDispatcher(executor=thread_exec)),
    ]

    print(f"{'dispatcher':<14} {'best_us':>10} {'mean_us':>10}")
    print("-" * 38)
    for label, disp in dispatchers:
        ev: Eventful[int] = Eventful(dispatcher=disp)
        for i in range(10):
            ev.subscribe(make_sub(i))
        best, mean = time_us(lambda e=ev: e.fire(42), iterations=2000, warmup=200)
        print(f"{label:<14} {best:>10.3f} {mean:>10.3f}")
    thread_exec.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Section 3: @task lifecycle breakdown
# ---------------------------------------------------------------------------


def section_task_lifecycle() -> None:
    banner("SECTION 3 -- @task() lifecycle breakdown (microseconds per call)")

    def bare(x: int) -> int:
        return x * 2

    # Reference -- bare call
    best_bare, mean_bare = time_us(lambda: bare(7), iterations=5000, warmup=500)

    # No observer
    decorated = task()(bare)
    best_no, mean_no = time_us(lambda: decorated(7), iterations=5000, warmup=500)

    # One TimingMeter
    decorated_t = task(on_execute=[TimingMeter()])(bare)
    best_t, mean_t = time_us(lambda: decorated_t(7), iterations=5000, warmup=500)

    # One MetricsMeter -- extractor returns a constant
    decorated_m = task(
        on_execute=[MetricsMeter(name="bench", extract=lambda ctx: 1.0)]
    )(bare)
    best_m, mean_m = time_us(lambda: decorated_m(7), iterations=5000, warmup=500)

    print(f"{'variant':<30} {'best_us':>10} {'mean_us':>10}")
    print("-" * 54)
    print(f"{'bare function call':<30} {best_bare:>10.3f} {mean_bare:>10.3f}")
    print(f"{'@task() no observer':<30} {best_no:>10.3f} {mean_no:>10.3f}")
    print(f"{'@task() + TimingMeter':<30} {best_t:>10.3f} {mean_t:>10.3f}")
    print(f"{'@task() + MetricsMeter':<30} {best_m:>10.3f} {mean_m:>10.3f}")

    # cProfile of the no-observer hot path to attribute the overhead
    print()
    print("-- cProfile of @task() no observer, 10k calls --")
    pr = cProfile.Profile()
    pr.enable()
    for i in range(10_000):
        decorated(i)
    pr.disable()
    print_pstats(pr, top=12)


# ---------------------------------------------------------------------------
# Section 4: WorkQueue throughput
# ---------------------------------------------------------------------------


def section_workqueue() -> None:
    banner("SECTION 4 -- WorkQueue enqueue + dequeue (50 batches of 100)")
    from callpyback import WorkQueue

    q = WorkQueue()
    TOPIC = "bench.workqueue"

    def enq_then_deq() -> None:
        for i in range(100):
            q.enqueue(TOPIC, i)
        for _ in range(100):
            q.dequeue(TOPIC, timeout=0)

    best, mean = time_us(enq_then_deq, iterations=50, warmup=5)
    print(f"100 enqueue + 100 dequeue  best={best:>10.3f} us  mean={mean:>10.3f} us")
    print(f"per op (best / 200): {best / 200:.3f} us")


# ---------------------------------------------------------------------------
# Section 5: MessageQueue in-memory roundtrip
# ---------------------------------------------------------------------------


def section_messagequeue() -> None:
    banner("SECTION 5 -- MessageQueue publish + receive, 5k roundtrips")

    q = MessageQueue()
    received: list[Any] = []

    def handler(msg: Any) -> None:
        received.append(msg)

    q.subscribe("topic.bench", handler)

    def pub() -> None:
        q.publish("topic.bench", {"x": 1})

    best, mean = time_us(pub, iterations=5000, warmup=500)
    print(f"publish() best={best:>10.3f} us  mean={mean:>10.3f} us")
    print(f"received {len(received)} messages (sanity check)")


# ---------------------------------------------------------------------------
# Section 6: Meter attach + Reporter lifecycle
# ---------------------------------------------------------------------------


def section_meter_reporter() -> None:
    banner("SECTION 6 -- Meter.attach() cost on a deep source class")

    class DeepSource:
        pass

    # Add many on_X channels to inflate the dir() walk in attach.
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
        # Meter has no public detach(); each call creates+attaches a new meter.
        m = MyMeter()
        m.attach(source)

    best, mean = time_us(create_and_attach, iterations=500, warmup=50)
    print(f"create + attach    best={best:>10.3f} us  mean={mean:>10.3f} us")

    # cProfile of attach() in isolation
    print()
    print("-- cProfile of 1000 Meter.attach(source) calls --")
    meters = [MyMeter() for _ in range(1000)]
    pr = cProfile.Profile()
    pr.enable()
    for m in meters:
        m.attach(source)
    pr.disable()
    print_pstats(pr, top=12)


# ---------------------------------------------------------------------------
# Section 7: tracemalloc -- sustained task dispatch
# ---------------------------------------------------------------------------


def section_tracemalloc() -> None:
    banner("SECTION 7 -- tracemalloc top allocators during 5000 @task() calls")

    def bare(x: int) -> int:
        return x * 2

    decorated = task()(bare)

    # Warm up
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
    print("-" * 72)
    for i, stat in enumerate(diff[:15], 1):
        loc = str(stat.traceback)
        print(f"{i:>4}  {stat.size_diff / 1024:>10.1f}  {stat.count_diff:>8}  {loc}")


# ---------------------------------------------------------------------------


def main() -> None:
    section_subscriber_sweep()
    section_dispatcher_comparison()
    section_task_lifecycle()
    section_workqueue()
    section_messagequeue()
    section_meter_reporter()
    section_tracemalloc()


if __name__ == "__main__":
    main()
