"""Tests for callpyback.observers module."""

import time

import pytest

from callpyback import (
    CallbackObserver,
    CompositeObserver,
    CPUObserver,
    ExecutionContext,
    LoggingObserver,
    MemoryObserver,
    Meter,
    MeterObserver,
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


class TestLoggingObserver:
    def test_logging_observer_basic(self, caplog):
        import logging

        caplog.set_level(logging.INFO)
        logging_obs = LoggingObserver()

        @observe(logging_obs)
        def my_func():
            return 42

        my_func()

        assert "Calling my_func" in caplog.text
        assert "completed" in caplog.text

    def test_logging_observer_with_args(self, caplog):
        import logging

        caplog.set_level(logging.INFO)
        logging_obs = LoggingObserver(log_args=True)

        @observe(logging_obs)
        def add(a, b):
            return a + b

        add(1, 2)

        assert "args=(1, 2)" in caplog.text


class TestMemoryObserver:
    def test_tracks_memory(self):
        memory = MemoryObserver()

        @observe(memory)
        def allocate():
            data = [i for i in range(10000)]
            return len(data)

        result = allocate()

        assert result == 10000
        if memory.measurements:
            assert memory.measurements[0]["peak"] > 0


class TestCPUObserver:
    def test_tracks_cpu(self):
        cpu = CPUObserver()

        @observe(cpu)
        def cpu_work():
            return sum(i**2 for i in range(10000))

        cpu_work()

        stats = cpu.stats
        assert stats["count"] == 1


class TestMeter:
    def test_basic_meter(self):
        meter = Meter("loss")

        meter.update(0.5)
        meter.update(0.3)
        meter.update(0.2)

        assert meter.count == 3
        assert meter.avg == pytest.approx(1.0 / 3)

    def test_weighted_meter(self):
        meter = Meter("loss")

        meter.update(0.5, n=10)
        meter.update(0.3, n=20)

        assert meter.count == 30
        assert meter.avg == pytest.approx((0.5 * 10 + 0.3 * 20) / 30)

    def test_reset(self):
        meter = Meter("test")

        meter.update(1.0)
        meter.update(2.0)

        meter.reset()

        assert meter.count == 0
        assert meter.avg == 0


class TestMeterObserver:
    def test_meter_observer_basic(self):
        meter_obs = MeterObserver(
            {
                "loss": lambda ctx: ctx.result.get("loss") if ctx.result else None,
            }
        )

        @observe(meter_obs)
        def train_step():
            return {"loss": 0.5}

        train_step()
        train_step()

        assert meter_obs.get_meter("loss").count == 2
        assert meter_obs.get_meter("loss").avg == 0.5


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


class TestCustomObserver:
    """Test that users can extend Observer for custom profiling."""

    def test_custom_observer(self):
        class CustomObserver(Observer):
            def __init__(self):
                self.start_count = 0
                self.end_count = 0

            def on_start(self, ctx):
                self.start_count += 1
                ctx.metadata["custom_start"] = True

            def on_end(self, ctx):
                self.end_count += 1
                ctx.metadata["custom_end"] = True

        custom = CustomObserver()

        @observe(custom)
        def my_func():
            return 42

        my_func()

        assert custom.start_count == 1
        assert custom.end_count == 1
