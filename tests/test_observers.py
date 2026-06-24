"""Tests for Observable / Eventful / Meter / Reporter and dispatchers."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from eventforge import (
    BroadcastDispatcher,
    ConcurrentDispatcher,
    Eventful,
    ExecutionContext,
    LeastLoadedDispatcher,
    Meter,
    MetricsMeter,
    Node,
    Observable,
    Reporter,
    RoundRobinDispatcher,
    TimingMeter,
    observe,
)

# =============================================================================
# Eventful primitive
# =============================================================================


class TestEventful:
    def test_subscribe_and_fire(self):
        e = Eventful()
        results = []
        e.on(lambda x: results.append(x))
        e.fire(42)
        assert results == [42]

    def test_broadcast_to_multiple_subscribers(self):
        e = Eventful()
        a, b = [], []
        e.on(lambda x: a.append(x))
        e.on(lambda x: b.append(x))
        e.fire("hello")
        assert a == ["hello"]
        assert b == ["hello"]

    def test_unsubscribe(self):
        e = Eventful()
        results = []
        fn = e.on(lambda x: results.append(x))
        e.fire(1)
        assert e.unsubscribe(fn) is True
        e.fire(2)
        assert results == [1]

    def test_failing_subscriber_does_not_stop_chain(self):
        e = Eventful()
        ok = []

        def bad(x):
            raise RuntimeError("boom")

        e.on(bad)
        e.on(lambda x: ok.append(x))
        e.fire("ping")
        assert ok == ["ping"]

    def test_round_robin_dispatch(self):
        e = Eventful(dispatcher=RoundRobinDispatcher())
        seen = []
        for i in range(3):
            e.on(lambda v, _i=i: seen.append((_i, v)))
        for v in [10, 20, 30, 40]:
            e.fire(v)
        assert seen == [(0, 10), (1, 20), (2, 30), (0, 40)]


# =============================================================================
# Observable string-keyed routing
# =============================================================================


class _DemoObservable(Observable):
    def __init__(self):
        self.alpha = Eventful()
        self.beta = Eventful()


class TestObservable:
    def test_string_subscribe_routes_to_attribute(self):
        obj = _DemoObservable()
        seen = []
        obj.on("alpha", lambda v: seen.append(v))
        obj.alpha.fire(7)
        assert seen == [7]

    def test_string_fire_routes_to_attribute(self):
        obj = _DemoObservable()
        seen = []
        obj.beta.on(lambda v: seen.append(v))
        obj.fire("beta", 99)
        assert seen == [99]

    def test_unknown_event_raises(self):
        obj = _DemoObservable()
        with pytest.raises(AttributeError):
            obj.on("gamma", lambda v: None)
        with pytest.raises(AttributeError):
            obj.fire("gamma", 1)

    def test_events_lists_eventful_attributes(self):
        obj = _DemoObservable()
        assert set(obj.events()) == {"alpha", "beta"}


# =============================================================================
# Dispatchers
# =============================================================================


class TestDispatchers:
    def test_broadcast_calls_all(self):
        seen = []
        BroadcastDispatcher().dispatch(
            [lambda x: seen.append(("a", x)), lambda x: seen.append(("b", x))],
            (5,),
            {},
        )
        assert seen == [("a", 5), ("b", 5)]

    def test_concurrent_uses_executor(self):
        with ThreadPoolExecutor(2) as pool:
            seen = []
            lock = threading.Lock()

            def slow(x):
                time.sleep(0.01)
                with lock:
                    seen.append(x)

            ConcurrentDispatcher(pool).dispatch([slow, slow], (1,), {})
            pool.shutdown(wait=True)
            assert seen == [1, 1]

    def test_least_loaded_picks_least_busy(self):
        class FakeNode:
            def __init__(self, load_val):
                self.load_val = load_val
                self.calls = 0

            def load(self):
                return self.load_val

            def __call__(self, *a, **kw):
                self.calls += 1

        n1, n2, n3 = FakeNode(0.8), FakeNode(0.3), FakeNode(0.5)
        LeastLoadedDispatcher().dispatch([n1, n2, n3], (), {})
        assert n2.calls == 1
        assert n1.calls == n3.calls == 0

    def test_least_loaded_raises_when_all_saturated(self):
        class Sat:
            def load(self):
                return 1.0

            def __call__(self, *a, **kw):
                pass

        with pytest.raises(RuntimeError, match="saturated"):
            LeastLoadedDispatcher().dispatch([Sat(), Sat()], (), {})


# =============================================================================
# Node
# =============================================================================


class TestNode:
    def test_capacity_from_gpus(self):
        n = Node("w", cpus=16, memory_gb=64, gpus=[0, 1], handler=lambda: None)
        assert n.capacity == 2

    def test_capacity_from_cpus_when_no_gpu(self):
        n = Node("w", cpus=8, memory_gb=16, gpus=[], handler=lambda: None)
        assert n.capacity == 2

    def test_load_tracks_inflight(self):
        started = threading.Event()
        released = threading.Event()

        def slow():
            started.set()
            released.wait(timeout=2.0)

        n = Node("w", cpus=4, memory_gb=8, gpus=[0], handler=slow)
        t = threading.Thread(target=n)
        t.start()
        started.wait(timeout=1.0)
        assert n.load() == 1.0
        released.set()
        t.join(timeout=2.0)
        assert n.load() == 0.0

    def test_try_acquire_respects_capacity(self):
        n = Node("w", cpus=4, memory_gb=8, gpus=[0, 1], handler=lambda: None)
        assert n.capacity == 2
        assert n.try_acquire() is True  # 1/2
        assert n.load() == 0.5
        assert n.try_acquire() is True  # 2/2
        assert n.load() == 1.0
        assert n.try_acquire() is False  # saturated, state unchanged
        assert n.load() == 1.0
        n.release()
        assert n.load() == 0.5
        assert n.try_acquire() is True

    def test_release_never_goes_negative(self):
        n = Node("w", cpus=4, memory_gb=8, gpus=[0], handler=lambda: None)
        n.release()
        n.release()
        assert n.load() == 0.0
        assert n.try_acquire() is True

    def test_try_acquire_is_atomic_under_contention(self):
        # Capacity-1 node hammered by many threads: exactly one wins per slot.
        n = Node("w", cpus=4, memory_gb=8, gpus=[0], handler=lambda: None)
        wins = []
        barrier = threading.Barrier(20)

        def race():
            barrier.wait()
            if n.try_acquire():
                wins.append(1)

        threads = [threading.Thread(target=race) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)
        assert sum(wins) == 1  # never double-booked


# =============================================================================
# Meter
# =============================================================================


class TestMeter:
    def test_aggregator_default_mean(self):
        m = Meter("loss")  # default reduction="mean"
        m.update(2.0)
        m.update(4.0)
        m.update(6.0)
        assert m.stats == {"value": 4.0, "count": 3.0}
        assert m.reduction == "mean"

    def test_reduction_max(self):
        m = Meter("peak", reduction="max")
        m.update(2.0)
        m.update(6.0)
        m.update(4.0)
        assert m.value == 6.0
        assert m.stats == {"value": 6.0, "count": 3.0}

    def test_unknown_reduction_raises(self):
        with pytest.raises(ValueError):
            Meter("x", reduction="bogus")

    def test_reset_clears_state(self):
        m = Meter("x")
        m.update(5.0)
        m.reset()
        assert m.stats == {"value": 0.0, "count": 0.0}

    def test_update_event_fires(self):
        m = Meter("y")
        seen = []
        m.update_event.on(lambda meter, val, n: seen.append((meter.name, val, n)))
        m.update(7.0, n=2)
        assert seen == [("y", 7.0, 2)]

    def test_measurement_fires_on_success(self):
        class _MyMeter(Meter):
            def measure(self, ctx):
                return 0.99

        m = _MyMeter("acc")
        seen = []
        m.measurement.on(lambda meter, val, ctx: seen.append((meter.name, val)))

        ctx = ExecutionContext(func_name="t", args=(), kwargs={})
        m.on_success(ctx)
        assert seen == [("acc", 0.99)]
        assert m.stats["count"] == 1
        assert ctx.metadata["acc"] == 0.99


class TestMeterAttach:
    def test_attach_wires_on_success(self):
        m = Meter("x")
        seen = []
        m.measurement.on(lambda meter, val, ctx: seen.append("fired"))

        class Source(Observable):
            def __init__(self):
                self.start = Eventful()
                self.success = Eventful()
                self.failure = Eventful()
                self.complete = Eventful()

        src = Source()
        m.attach(src)

        ctx = ExecutionContext(func_name="t", args=(), kwargs={})
        src.success.fire(ctx)
        assert seen == ["fired"]


# =============================================================================
# Reporter @observe wiring
# =============================================================================


class TestReporter:
    def test_observe_binds_method_to_class_events(self):
        seen = []

        class _MyReporter(Reporter):
            @observe(TimingMeter, "measurement")
            def on_timing(self, meter, val, ctx):
                seen.append((meter.name, val))

        _MyReporter()  # auto-wires bound method

        t = TimingMeter()
        ctx = ExecutionContext(
            func_name="t",
            args=(),
            kwargs={},
            start_time=time.perf_counter() - 0.001,
        )
        t.on_start(ctx)
        t.on_success(ctx)
        assert seen and seen[0][0] == "timing"


# =============================================================================
# Concrete meters
# =============================================================================


class TestConcreteMeters:
    def test_timing_meter_measures_elapsed(self):
        m = TimingMeter()
        ctx = ExecutionContext(func_name="t", args=(), kwargs={})
        m.on_start(ctx)
        time.sleep(0.005)
        m.on_success(ctx)
        assert m.stats["count"] == 1
        assert m.stats["value"] >= 0.004

    def test_metrics_meter_extracts(self):
        m = MetricsMeter("loss", extract=lambda ctx: ctx.result["loss"])
        ctx = ExecutionContext(
            func_name="t",
            args=(),
            kwargs={},
            result={"loss": 0.42},
        )
        m.on_success(ctx)
        assert m.stats["value"] == 0.42
