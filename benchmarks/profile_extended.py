#!/usr/bin/env python
"""Extended profiling for observer-pattern (v2).

Picks up where ``profile_components.py`` leaves off. Seven new sections:

  1. Topic x subscriber grid for MessageQueue.publish (validates O(1)
     sub-id -> topic index at scale).
  2. Pattern matching cost: exact vs single-* vs ** wildcards.
  3. TaskPool acquire/release overhead with vs without max_instances.
  4. Reporter @observe auto-wiring lifecycle.
  5. Executor modes: SEQUENTIAL vs THREAD submit + result roundtrip.
  6. MessageQueue payload size sweep.
  7. Subscribe / unsubscribe churn for MessageQueue and MemoryTransport.

Skips: TCP, process-mode Executor.

Run::

    PYTHONPATH=. python benchmarks/profile_extended.py
    PYTHONPATH=. python benchmarks/profile_extended.py --output baseline.json
    PYTHONPATH=. python benchmarks/profile_extended.py --baseline baseline.json --strict
"""

from __future__ import annotations

import cProfile
import io
import pstats
import sys
from pathlib import Path

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
from callpyback.task import TaskPool
from callpyback.transports.memory import MemoryTransport

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


def section_topic_sub_grid(suite: BenchSuite) -> None:
    banner("SECTION 1 -- MessageQueue.publish vs topic count x subscriber count")

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
        for ti in range(n_topics):
            topic = f"bench.topic.{ti}"
            for _ in range(subs_per_topic):
                q.subscribe(topic, make_handler())
        target_topic = "bench.topic.0"
        suite.measure(
            f"publish topics={n_topics:<4} subs/topic={subs_per_topic:<3}",
            lambda q=q, t=target_topic: q.publish(t, {"x": 1}),
            iterations=500,
            warmup=50,
        )


def section_pattern_matching(suite: BenchSuite) -> None:
    banner("SECTION 2 -- subscribe pattern: exact vs single-* vs **")
    cases = {
        "exact": "bench.exact.topic",
        "single-* glob": "bench.exact.*",
        "trailing **": "bench.**",
        "leading *": "*.exact.topic",
    }
    target = "bench.exact.topic"
    for label, pattern in cases.items():
        q = MessageQueue()

        def handler(msg):
            pass

        q.subscribe(pattern, handler)
        suite.measure(
            f"pattern: {label}",
            lambda q=q, t=target: q.publish(t, 1),
            iterations=2000,
            warmup=200,
        )


def section_taskpool(suite: BenchSuite) -> None:
    banner("SECTION 3 -- TaskPool acquire/release vs uncontested")

    def bare(x: int) -> int:
        return x

    decorated_no_pool = task()(bare)
    suite.measure(
        "@task() no pool",
        lambda: decorated_no_pool(7),
        iterations=2000,
        warmup=200,
    )

    decorated_pool = task(max_instances=1000)(bare)
    suite.measure(
        "@task() max_instances=1000",
        lambda: decorated_pool(7),
        iterations=2000,
        warmup=200,
    )

    print()
    print("-- cProfile of 5000 TaskPool.acquire+release (max_instances=10) --")
    pool = TaskPool(max_instances=10)
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(5000):
        pool.acquire()
        pool.release()
    pr.disable()
    _print_pstats(pr, top=10)


def section_reporter_lifecycle(suite: BenchSuite) -> None:
    banner("SECTION 4 -- Reporter @observe auto-wiring")
    from callpyback import Reporter, observe

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

    suite.measure(
        "Reporter() with 2 @observe",
        lambda: TwoEventReporter(),
        iterations=500,
        warmup=50,
    )

    print()
    print("-- cProfile of 1000 Reporter() instantiations --")
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(1000):
        TwoEventReporter()
    pr.disable()
    _print_pstats(pr, top=10)


def section_executor_modes(suite: BenchSuite) -> None:
    banner("SECTION 5 -- Executor submit + result roundtrip")
    from callpyback import ExecutionMode, Executor

    def trivial(x: int) -> int:
        return x

    for label, mode in [
        ("SEQUENTIAL", ExecutionMode.SEQUENTIAL),
        ("THREAD", ExecutionMode.THREAD),
    ]:
        executor = Executor(mode=mode)
        try:

            def roundtrip(e=executor):
                tid = e.submit(trivial, 7)
                e.result(tid)

            suite.measure(
                f"Executor.{label:<11}", roundtrip, iterations=500, warmup=50
            )
        finally:
            close = getattr(executor, "shutdown", None) or getattr(
                executor, "close", None
            )
            if close is not None:
                try:
                    close()
                except Exception:
                    pass


def section_payload_size(suite: BenchSuite) -> None:
    banner("SECTION 6 -- MessageQueue.publish vs payload size")
    sizes = {
        "scalar int": 1,
        "small dict (3)": {"a": 1, "b": 2, "c": 3},
        "med dict (20)": {f"k{i}": i for i in range(20)},
        "1KB blob": "x" * 1024,
        "64KB blob": "x" * (64 * 1024),
        "list[100] ints": list(range(100)),
    }
    for label, payload in sizes.items():
        q = MessageQueue()

        def handler(msg):
            pass

        q.subscribe("bench.payload", handler)
        suite.measure(
            f"payload: {label:<14}",
            lambda q=q, p=payload: q.publish("bench.payload", p),
            iterations=1000,
            warmup=100,
        )


def section_sub_unsub_churn(suite: BenchSuite) -> None:
    banner("SECTION 7 -- subscribe + unsubscribe lifecycle churn")

    def handler(msg):
        pass

    q = MessageQueue()

    def mq_churn():
        sub_id = q.subscribe("bench.churn", handler)
        q.unsubscribe(sub_id)

    suite.measure("MessageQueue sub+unsub", mq_churn, iterations=2000, warmup=200)

    t = MemoryTransport()

    def tr_churn():
        sub_id = t.subscribe("bench.churn", handler)
        t.unsubscribe(sub_id)

    suite.measure("MemoryTransport sub+unsub", tr_churn, iterations=2000, warmup=200)

    print()
    print("-- cProfile of 5000 MessageQueue sub+unsub cycles --")
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(5000):
        sub_id = q.subscribe("bench.cprof", handler)
        q.unsubscribe(sub_id)
    pr.disable()
    _print_pstats(pr, top=10)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    args = parse_args()
    suite = BenchSuite(name="observer-pattern.profile_extended", cli=args)

    section_topic_sub_grid(suite)
    section_pattern_matching(suite)
    section_taskpool(suite)
    section_reporter_lifecycle(suite)
    section_executor_modes(suite)
    section_payload_size(suite)
    section_sub_unsub_churn(suite)

    banner("ASSERT_WITHIN GATES")
    suite.assert_within("publish topics=1    subs/topic=1  ", 50.0)  # us
    suite.assert_within("publish topics=100  subs/topic=1  ", 150.0)  # us
    suite.assert_within("Reporter() with 2 @observe", 20.0)  # us, post-cache floor ~3.6 us
    suite.assert_within("Executor.THREAD     ", 100.0)  # us, post-ThreadPool overhead ~46 us

    return finalize(suite)


if __name__ == "__main__":
    sys.exit(main())
