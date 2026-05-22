#!/usr/bin/env python
"""cProfile the in-process dispatch hot paths.

Complements ``callpyback_bench.py`` (which reports median/p95 latencies) by
attributing time inside dispatch to specific functions. Skips the TCP
roundtrip path because cProfile is not useful for socket I/O.

Three workloads:

  A. Raw ``Eventful.fire`` with 3 subscribers
  B. ``@task()`` lifecycle with no observers attached
  C. ``@task()`` lifecycle with one ``TimingMeter`` attached

Run::

    PYTHONPATH=. python benchmarks/profile_dispatch.py
"""

from __future__ import annotations

import cProfile
import io
import pstats

from callpyback import TimingMeter, task
from callpyback.observers import Eventful


def workload_a_eventful_dispatch(iterations: int = 50_000) -> None:
    ev: Eventful[int] = Eventful()
    captured: list[int] = []

    def sub1(x: int) -> None:
        captured.append(x)

    def sub2(x: int) -> None:
        captured.append(x + 1)

    def sub3(x: int) -> None:
        captured.append(x + 2)

    ev.subscribe(sub1)
    ev.subscribe(sub2)
    ev.subscribe(sub3)

    for i in range(iterations):
        ev.fire(i)


def workload_b_task_no_obs(iterations: int = 20_000) -> None:
    def bare(x: int) -> int:
        return x * 2

    decorated = task()(bare)
    for i in range(iterations):
        decorated(i)


def workload_c_task_with_obs(iterations: int = 20_000) -> None:
    def bare(x: int) -> int:
        return x * 2

    timing = TimingMeter()
    decorated = task(on_execute=[timing])(bare)
    for i in range(iterations):
        decorated(i)


def profile_workload(label: str, fn) -> None:
    # Warm up so import-time / first-call costs do not dominate.
    fn()
    pr = cProfile.Profile()
    pr.enable()
    fn()
    pr.disable()
    print("#" * 70)
    print(f"# WORKLOAD: {label}")
    print("#" * 70)
    for sort_key, header in (
        ("cumulative", "by cumulative time"),
        ("tottime", "by internal time"),
    ):
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats(sort_key)
        ps.print_stats(20)
        print(f"-- {header} --")
        print(s.getvalue())


def main() -> None:
    profile_workload(
        "A. Eventful.fire 50k dispatches, 3 subscribers",
        workload_a_eventful_dispatch,
    )
    profile_workload("B. @task() no observer, 20k calls", workload_b_task_no_obs)
    profile_workload(
        "C. @task() with TimingMeter, 20k calls", workload_c_task_with_obs
    )


if __name__ == "__main__":
    main()
