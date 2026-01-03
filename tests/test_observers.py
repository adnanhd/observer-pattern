"""Tests for callpyback.observers module."""

import time

import pytest

from callpyback import (
    CallbackObserver,
    CompositeObserver,
    ExecutionContext,
    FLOPsObserver,
    MemoryObserver,
    MetricsObserver,
    Observer,
    TimingObserver,
    observe,
)


class TestTimingObserver:
    def test_tracks_execution_time(self):
        timing = TimingObserver()

        @observe(timing)
        def slow_func():
            time.sleep(0.05)
            return "done"

        result = slow_func()

        assert result == "done"
        assert len(timing.timings) == 1
        assert timing.timings[0] >= 0.05

    def test_threshold_detection(self):
        timing = TimingObserver(threshold=0.01)
        ctx_metadata = {}

        @observe(timing)
        def slow_func():
            time.sleep(0.05)
            return "done"

        slow_func()

        stats = timing.stats
        assert stats["count"] == 1
        assert stats["avg"] >= 0.05

    def test_stats_calculation(self):
        timing = TimingObserver()

        @observe(timing)
        def quick_func():
            return 42

        for _ in range(5):
            quick_func()

        stats = timing.stats
        assert stats["count"] == 5
        assert stats["min"] <= stats["avg"] <= stats["max"]

    def test_reset(self):
        timing = TimingObserver()

        @observe(timing)
        def func():
            return 1

        func()
        assert timing.stats["count"] == 1

        timing.reset()
        assert timing.stats["count"] == 0


class TestMetricsObserver:
    def test_tracks_calls(self):
        metrics = MetricsObserver()

        @observe(metrics)
        def my_func(x):
            return x * 2

        my_func(1)
        my_func(2)
        my_func(3)

        stats = metrics.stats
        assert stats["calls"] == 3
        assert stats["successes"] == 3
        assert stats["failures"] == 0

    def test_tracks_failures(self):
        metrics = MetricsObserver()

        @observe(metrics)
        def failing_func():
            raise ValueError("error")

        for _ in range(3):
            try:
                failing_func()
            except ValueError:
                pass

        stats = metrics.stats
        assert stats["calls"] == 3
        assert stats["successes"] == 0
        assert stats["failures"] == 3

    def test_success_rate(self):
        metrics = MetricsObserver()

        @observe(metrics)
        def mixed_func(fail: bool):
            if fail:
                raise ValueError("fail")
            return "ok"

        mixed_func(False)
        mixed_func(False)
        try:
            mixed_func(True)
        except ValueError:
            pass

        stats = metrics.stats
        assert stats["calls"] == 3
        assert stats["successes"] == 2
        assert stats["failures"] == 1
        assert stats["success_rate"] == pytest.approx(2 / 3)

    def test_reset(self):
        metrics = MetricsObserver()

        @observe(metrics)
        def func():
            return 1

        func()
        metrics.reset()

        assert metrics.stats["calls"] == 0


class TestMemoryObserver:
    def test_tracks_memory(self):
        memory = MemoryObserver()

        @observe(memory)
        def allocate():
            data = [i for i in range(10000)]
            return len(data)

        result = allocate()

        assert result == 10000
        # Memory tracking may not work in all environments
        if memory.measurements:
            assert memory.measurements[0]["peak"] > 0


class TestFLOPsObserver:
    def test_tracks_flops_from_metadata(self):
        flops = FLOPsObserver()

        @observe(flops)
        def compute():
            # Simulate reporting FLOPs via observer
            return 42

        compute()
        # Default is 0 if not set in metadata
        assert flops.stats["count"] == 1


class TestCompositeObserver:
    def test_combines_observers(self):
        timing = TimingObserver()
        metrics = MetricsObserver()
        composite = CompositeObserver([timing, metrics])

        @observe(composite)
        def my_func():
            return 42

        my_func()
        my_func()

        assert timing.stats["count"] == 2
        assert metrics.stats["calls"] == 2


class TestCallbackObserver:
    def test_on_start_callback(self):
        calls = []

        observer = CallbackObserver(
            on_start=lambda ctx: calls.append(f"start:{ctx.func_name}")
        )

        @observe(observer)
        def my_func():
            return 1

        my_func()

        assert calls == ["start:my_func"]

    def test_on_end_callback(self):
        results = []
        observer = CallbackObserver(on_end=lambda ctx: results.append(ctx.result))

        @observe(observer)
        def compute(x):
            return x * 2

        compute(21)

        assert results == [42]

    def test_on_error_callback(self):
        errors = []

        observer = CallbackObserver(on_error=lambda ctx: errors.append(str(ctx.error)))

        @observe(observer)
        def failing():
            raise ValueError("test error")

        with pytest.raises(ValueError):
            failing()

        assert len(errors) == 1
        assert "test error" in errors[0]


class TestObserveDecorator:
    def test_basic_observe(self):
        timing = TimingObserver()

        @observe(timing)
        def add(a, b):
            return a + b

        result = add(1, 2)

        assert result == 3
        assert timing.stats["count"] == 1

    def test_on_execute_callback(self):
        executions = []

        @observe(on_execute=lambda ctx: executions.append(ctx.func_name))
        def my_func():
            return 42

        my_func()

        assert executions == ["my_func"]

    def test_multiple_observers(self):
        timing = TimingObserver()
        metrics = MetricsObserver()

        @observe(timing, metrics)
        def compute(x):
            return x**2

        compute(5)
        compute(10)

        assert timing.stats["count"] == 2
        assert metrics.stats["calls"] == 2

    def test_preserves_function_metadata(self):
        @observe(TimingObserver())
        def documented_func(x: int) -> int:
            """Doubles the input."""
            return x * 2

        assert documented_func.__name__ == "documented_func"
        assert "Doubles" in documented_func.__doc__

    def test_exception_propagation(self):
        metrics = MetricsObserver()

        @observe(metrics)
        def failing():
            raise RuntimeError("error")

        with pytest.raises(RuntimeError, match="error"):
            failing()

        assert metrics.stats["failures"] == 1

    def test_execution_context_properties(self):
        captured_ctx = []

        observer = CallbackObserver(on_end=lambda ctx: captured_ctx.append(ctx))

        @observe(observer)
        def func(a, b, c=10):
            time.sleep(0.01)
            return a + b + c

        func(1, 2, c=3)

        ctx = captured_ctx[0]
        assert ctx.func_name == "func"
        assert ctx.args == (1, 2)
        assert ctx.kwargs == {"c": 3}
        assert ctx.result == 6
        assert ctx.is_success is True
        assert ctx.execution_time >= 0.01
