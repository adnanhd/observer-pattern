#!/usr/bin/env python
"""Extended profiling for observer-pattern.

Picks up where ``profile_components.py`` leaves off. Covers seven angles
the comprehensive profile missed:

  1. Topic x subscriber grid for MessageQueue.publish -- validates the
     O(N) sub-id -> topic index added in ``transports/memory.py``.
  2. Pattern-matching cost: exact-match vs single-* vs ** wildcards.
  3. TaskPool overhead with vs without max_instances under contention.
  4. Reporter @observe auto-wiring lifecycle (mirror of Meter.attach).
  5. Executor modes: SEQUENTIAL vs THREAD submit + result roundtrip.
  6. MessageQueue payload size sweep (small vs medium vs large).
  7. Subscribe / unsubscribe churn (lifecycle perf of the registration
     path itself).

Skips: TCP transport, process-mode Executor -- cProfile is not useful
for socket I/O or fork overhead.

Run::

    PYTHONPATH=. python benchmarks/profile_extended.py
"""

from __future__ import annotations

import cProfile
import gc
import io
import pstats
import threading
import time
from typing import Any

from callpyback import (
    ExecutionMode,
    Executor,
    Meter,
    MessageQueue,
    Reporter,
    observe,
    task,
)
from callpyback.task import TaskPool
from callpyback.transports.memory import MemoryTransport

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


def time_us(fn, iterations: int, warmup: int = 50) -> tuple:
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
# Section 1: topic x subscriber grid (validates Win 2 at scale)
# ---------------------------------------------------------------------------


def section_topic_sub_grid() -> None:
    banner("SECTION 1 -- MessageQueue.publish vs topic count x subscriber count")
    print(f"{'topics':>8} {'subs/topic':>11} {'best_us':>10} {'mean_us':>10}")
    print("-" * 46)

    def make_handler():
        captured = []

        def handler(msg):
            captured.append(msg)

        return handler

    for n_topics, subs_per_topic in [
        (1, 1),
        (1, 10),
        (10, 1),
        (10, 10),
        (50, 5),
        (100, 1),
        (100, 5),
    ]:
        q = MessageQueue()
        # Pre-subscribe across many topics.
        for ti in range(n_topics):
            topic = f"bench.topic.{ti}"
            for _ in range(subs_per_topic):
                q.subscribe(topic, make_handler())
        target_topic = "bench.topic.0"
        best, mean = time_us(
            lambda q=q, t=target_topic: q.publish(t, {"x": 1}),
            iterations=500,
            warmup=50,
        )
        print(f"{n_topics:>8} {subs_per_topic:>11} {best:>10.3f} {mean:>10.3f}")


# ---------------------------------------------------------------------------
# Section 2: pattern matching cost
# ---------------------------------------------------------------------------


def section_pattern_matching() -> None:
    banner("SECTION 2 -- subscribe pattern: exact vs single-* vs **")

    cases = {
        "exact            ": "bench.exact.topic",
        "single-* glob    ": "bench.exact.*",
        "trailing **      ": "bench.**",
        "leading *        ": "*.exact.topic",
    }
    target = "bench.exact.topic"
    print(f"{'pattern':<18} {'best_us':>10} {'mean_us':>10}")
    print("-" * 42)
    for label, pattern in cases.items():
        q = MessageQueue()

        def handler(msg):
            pass

        q.subscribe(pattern, handler)
        best, mean = time_us(
            lambda q=q, t=target: q.publish(t, 1), iterations=2000, warmup=200
        )
        print(f"{label:<18} {best:>10.3f} {mean:>10.3f}")


# ---------------------------------------------------------------------------
# Section 3: TaskPool overhead
# ---------------------------------------------------------------------------


def section_taskpool() -> None:
    banner("SECTION 3 -- TaskPool acquire/release vs uncontested")

    # No-pool baseline (just measure raw @task() cost for reference).
    def bare(x: int) -> int:
        return x

    decorated_no_pool = task()(bare)
    best, mean = time_us(lambda: decorated_no_pool(7), iterations=2000, warmup=200)
    print(f"{'@task() no pool':<28} best={best:>10.3f} us  mean={mean:>10.3f} us")

    # With max_instances=1000 (essentially uncontested -- pool always has a slot).
    decorated_pool = task(max_instances=1000)(bare)
    best, mean = time_us(lambda: decorated_pool(7), iterations=2000, warmup=200)
    print(
        f"{'@task() max_instances=1000':<28} best={best:>10.3f} us  mean={mean:>10.3f} us"
    )

    # cProfile the pool acquire/release path in isolation.
    print()
    print("-- cProfile of 5000 TaskPool.acquire+release (max_instances=10) --")
    pool = TaskPool(max_instances=10)
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(5000):
        pool.acquire()
        pool.release()
    pr.disable()
    print_pstats(pr, top=10)


# ---------------------------------------------------------------------------
# Section 4: Reporter @observe lifecycle
# ---------------------------------------------------------------------------


def section_reporter_lifecycle() -> None:
    banner("SECTION 4 -- Reporter @observe auto-wiring vs Meter.attach")

    class TargetMeter(Meter):
        name = "target"

        def measure(self, ctx):
            return 1.0

    class TwoEventReporter(Reporter):
        @observe(TargetMeter, "measurement")
        def on_measurement(self, *args, **kwargs):
            pass

        @observe(TargetMeter, "lifecycle")
        def on_lifecycle(self, *args, **kwargs):
            pass

    # Reporter init does the auto-wiring; measure construction cost only
    # since there is no public detach.
    def create_reporter():
        TwoEventReporter()

    best, mean = time_us(create_reporter, iterations=500, warmup=50)
    print(f"Reporter() with 2 @observe methods  best={best:>10.3f} us  mean={mean:>10.3f} us")

    # cProfile the Reporter init pipeline.
    print()
    print("-- cProfile of 1000 Reporter() instantiations --")
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(1000):
        TwoEventReporter()
    pr.disable()
    print_pstats(pr, top=10)


# ---------------------------------------------------------------------------
# Section 5: Executor modes
# ---------------------------------------------------------------------------


def section_executor_modes() -> None:
    banner("SECTION 5 -- Executor submit + result roundtrip")
    print(f"{'mode':<14} {'best_us':>10} {'mean_us':>10}")
    print("-" * 38)

    def trivial(x: int) -> int:
        return x

    for label, mode in [
        ("SEQUENTIAL", ExecutionMode.SEQUENTIAL),
        ("THREAD     ", ExecutionMode.THREAD),
    ]:
        executor = Executor(mode=mode)
        try:

            def roundtrip(e=executor):
                tid = e.submit(trivial, 7)
                e.result(tid)

            best, mean = time_us(roundtrip, iterations=500, warmup=50)
            print(f"{label:<14} {best:>10.3f} {mean:>10.3f}")
        finally:
            close = getattr(executor, "shutdown", None) or getattr(executor, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Section 6: MessageQueue payload size sweep
# ---------------------------------------------------------------------------


def section_payload_size() -> None:
    banner("SECTION 6 -- MessageQueue.publish vs payload size")

    sizes = {
        "scalar int    ": 1,
        "small dict (3)": {"a": 1, "b": 2, "c": 3},
        "med dict (20) ": {f"k{i}": i for i in range(20)},
        "1KB blob      ": "x" * 1024,
        "64KB blob     ": "x" * (64 * 1024),
        "list[100] ints": list(range(100)),
    }

    print(f"{'payload':<18} {'best_us':>10} {'mean_us':>10}")
    print("-" * 42)
    for label, payload in sizes.items():
        q = MessageQueue()

        def handler(msg):
            pass

        q.subscribe("bench.payload", handler)
        best, mean = time_us(
            lambda q=q, p=payload: q.publish("bench.payload", p),
            iterations=1000,
            warmup=100,
        )
        print(f"{label:<18} {best:>10.3f} {mean:>10.3f}")


# ---------------------------------------------------------------------------
# Section 7: subscribe / unsubscribe churn
# ---------------------------------------------------------------------------


def section_sub_unsub_churn() -> None:
    banner("SECTION 7 -- subscribe + unsubscribe lifecycle churn")

    def handler(msg):
        pass

    # MessageQueue path (goes through transport).
    q = MessageQueue()

    def mq_churn():
        sub_id = q.subscribe("bench.churn", handler)
        q.unsubscribe(sub_id)

    best, mean = time_us(mq_churn, iterations=2000, warmup=200)
    print(f"{'MessageQueue sub+unsub':<26} best={best:>10.3f} us  mean={mean:>10.3f} us")

    # Raw MemoryTransport (bypasses MessageQueue's index bookkeeping).
    t = MemoryTransport()

    def tr_churn():
        sub_id = t.subscribe("bench.churn", handler)
        t.unsubscribe(sub_id)

    best, mean = time_us(tr_churn, iterations=2000, warmup=200)
    print(f"{'MemoryTransport sub+unsub':<26} best={best:>10.3f} us  mean={mean:>10.3f} us")

    # cProfile the MQ churn path.
    print()
    print("-- cProfile of 5000 MessageQueue sub+unsub cycles --")
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(5000):
        sub_id = q.subscribe("bench.cprof", handler)
        q.unsubscribe(sub_id)
    pr.disable()
    print_pstats(pr, top=10)


# ---------------------------------------------------------------------------


def main() -> None:
    section_topic_sub_grid()
    section_pattern_matching()
    section_taskpool()
    section_reporter_lifecycle()
    section_executor_modes()
    section_payload_size()
    section_sub_unsub_churn()


if __name__ == "__main__":
    main()
