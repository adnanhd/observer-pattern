"""Tiny shared benchmark framework for the profile_* scripts in this dir.

Designed to be vendored verbatim into each repo's ``benchmarks/`` directory
(no cross-repo dependency). Provides:

  - ``Sample``: a frozen dataclass with best, mean, median, p95, stddev, n.
  - ``BenchSuite.measure(label, fn, ...)``: time a callable, collect a Sample.
  - JSON output of every collected Sample for trend tracking.
  - Baseline diff: load a prior JSON, print per-label delta (REG / WIN / -).
  - ``assert_within(label, limit)``: CI gate; fails the run if exceeded.
  - ``parse_args()``: ``--iterations-scale``, ``--output``, ``--baseline``,
    ``--strict``, ``--quiet``.

cProfile sections in the profilers are intentionally outside the
framework: they are about per-function attribution, not single-number
measurements, and pstats is already a reasonable formatter.

No third-party deps. ASCII only.
"""

from __future__ import annotations

import argparse
import gc
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional


# ---------------------------------------------------------------------------
# Sample: one measurement series
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sample:
    """One labeled measurement series with summary stats.

    ``unit`` is a free-form string ('us', 'ms', 's') so the formatter can
    render values without unit conversion. ``n`` is the number of timed
    iterations (excluding warmup).
    """

    label: str
    unit: str
    n: int
    best: float
    mean: float
    median: float
    p95: float
    stddev: float

    def format_line(self, label_width: int = 40) -> str:
        return (
            f"{self.label:<{label_width}} "
            f"best={self.best:>8.3f} {self.unit}  "
            f"med={self.median:>8.3f} {self.unit}  "
            f"p95={self.p95:>8.3f} {self.unit}  "
            f"sd={self.stddev:>7.3f}  "
            f"n={self.n}"
        )


def _summarize(samples_t: List[float], label: str, unit: str) -> Sample:
    samples_t_sorted = sorted(samples_t)
    n = len(samples_t_sorted)
    return Sample(
        label=label,
        unit=unit,
        n=n,
        best=samples_t_sorted[0],
        mean=sum(samples_t_sorted) / n,
        median=samples_t_sorted[n // 2],
        p95=samples_t_sorted[max(int(0.95 * n) - 1, 0)] if n >= 20 else samples_t_sorted[-1],
        stddev=statistics.stdev(samples_t_sorted) if n >= 2 else 0.0,
    )


# ---------------------------------------------------------------------------
# BenchSuite: accumulator across sections
# ---------------------------------------------------------------------------


@dataclass
class BenchSuite:
    """Accumulator for the whole profiler run.

    Pass the parsed CLI argparse namespace as ``cli`` so the framework can
    honor ``--iterations-scale`` etc. Set ``cli=None`` for in-script use.
    """

    name: str
    cli: Optional[argparse.Namespace] = None
    samples: List[Sample] = field(default_factory=list)
    _failures: List[str] = field(default_factory=list)

    def _scaled(self, iterations: int) -> int:
        scale = getattr(self.cli, "iterations_scale", 1.0) if self.cli else 1.0
        return max(int(iterations * scale), 5)

    def _quiet(self) -> bool:
        return bool(getattr(self.cli, "quiet", False)) if self.cli else False

    def measure(
        self,
        label: str,
        fn: Callable[[], Any],
        *,
        iterations: int,
        warmup: int = 5,
        unit: str = "us",
    ) -> Sample:
        """Time ``fn()`` ``iterations`` times after ``warmup`` warmups.

        cProfile is intentionally NOT involved here -- this is wall-clock.
        ``unit`` is 'us' or 'ms'; the timer scales accordingly. ``gc.collect``
        runs between samples to reduce variance from cycle collection bursts.
        """
        n = self._scaled(iterations)
        for _ in range(warmup):
            fn()
        mult = 1_000_000.0 if unit == "us" else 1000.0 if unit == "ms" else 1.0
        timings: List[float] = []
        for _ in range(n):
            gc.collect()
            t0 = time.perf_counter()
            fn()
            timings.append((time.perf_counter() - t0) * mult)
        s = _summarize(timings, label, unit)
        self.samples.append(s)
        if not self._quiet():
            print(s.format_line())
        return s

    def assert_within(self, label: str, max_value: float) -> None:
        """Fail the run (only if ``--strict``) when ``label``'s best exceeds the limit.

        Always prints a [PASS] / [FAIL] line. Without ``--strict`` the run
        continues so a single regression does not block the rest of the
        report.
        """
        s = next((s for s in self.samples if s.label == label), None)
        if s is None:
            print(f"[MISS] {label}: no sample with this label")
            self._failures.append(label)
            return
        ok = s.best <= max_value
        tag = "PASS" if ok else "FAIL"
        print(
            f"[{tag}] {label}: best={s.best:.3f} {s.unit} "
            f"limit={max_value:.3f} {s.unit}"
        )
        if not ok:
            self._failures.append(label)


# ---------------------------------------------------------------------------
# CLI + JSON + baseline diff
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="profile runner")
    p.add_argument(
        "--iterations-scale",
        type=float,
        default=1.0,
        help="Multiply every section's iteration count by this factor "
        "(e.g. 0.1 for a quick smoke run, 5.0 for a tight measurement).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write all collected samples to this path as JSON.",
    )
    p.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Compare collected samples against the JSON at this path; "
        "print a per-label regression table.",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.20,
        help="Fractional regression threshold for baseline diff "
        "(default 0.20 = 20 percent slower flagged as REG).",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any assert_within failed or any sample "
        "regressed past --threshold versus --baseline.",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-sample lines (still prints summary blocks).",
    )
    return p.parse_args(argv)


def write_json(suite: BenchSuite, path: Path) -> None:
    """Write the suite's samples to ``path`` as JSON.

    Schema is a flat list of Sample dicts. Stable across versions of this
    framework so saved baselines remain comparable.
    """
    path.write_text(
        json.dumps(
            {
                "name": suite.name,
                "samples": [asdict(s) for s in suite.samples],
            },
            indent=2,
        )
    )
    print(f"\nwrote {len(suite.samples)} samples to {path}")


def compare_baseline(
    suite: BenchSuite, baseline_path: Path, threshold: float = 0.2
) -> List[str]:
    """Print a per-label diff vs baseline; return list of regressed labels.

    A label is flagged REG if its current best is more than ``threshold``
    fraction slower than the baseline. WIN if more than ``threshold``
    faster. NEW if the label was not in the baseline.
    """
    data = json.loads(baseline_path.read_text())
    by_label = {s["label"]: s for s in data.get("samples", [])}
    regressed: List[str] = []
    print()
    print("=" * 78)
    print(f"baseline diff vs {baseline_path}  (threshold {threshold * 100:.0f}%)")
    print("=" * 78)
    print(f"{'label':<45} {'baseline':>10} {'current':>10} {'delta':>10}  tag")
    print("-" * 78)
    for s in suite.samples:
        b = by_label.get(s.label)
        if b is None:
            print(
                f"{s.label:<45} {'-':>10} {s.best:>10.3f} {'-':>10}  NEW"
            )
            continue
        b_best = float(b["best"])
        delta_pct = (s.best - b_best) / b_best * 100 if b_best > 0 else 0.0
        if delta_pct > threshold * 100:
            tag = "REG"
            regressed.append(s.label)
        elif delta_pct < -threshold * 100:
            tag = "WIN"
        else:
            tag = "ok"
        print(
            f"{s.label:<45} {b_best:>10.3f} {s.best:>10.3f} {delta_pct:>+9.1f}%  {tag}"
        )
    if regressed:
        print(f"\n{len(regressed)} regression(s): {', '.join(regressed)}")
    return regressed


def finalize(suite: BenchSuite) -> int:
    """Honor --output / --baseline / --strict on the parsed CLI; return exit code."""
    cli = suite.cli
    if cli is None:
        return 0
    if cli.output is not None:
        write_json(suite, cli.output)
    regressed: List[str] = []
    if cli.baseline is not None:
        regressed = compare_baseline(suite, cli.baseline, threshold=cli.threshold)
    fail = bool(suite._failures) or bool(regressed)
    if cli.strict and fail:
        print(
            f"\nstrict mode: {len(suite._failures)} assert_within failure(s), "
            f"{len(regressed)} regression(s) -- exiting 1"
        )
        return 1
    return 0


# ---------------------------------------------------------------------------
# Convenience: print a section banner
# ---------------------------------------------------------------------------


def banner(text: str) -> None:
    print()
    print("#" * 72)
    print(f"# {text}")
    print("#" * 72)


__all__ = [
    "Sample",
    "BenchSuite",
    "parse_args",
    "write_json",
    "compare_baseline",
    "finalize",
    "banner",
]
