"""Concurrency / thread-safety regression tests.

These exercise races found by a concurrency audit of eventforge: Meter
aggregation under concurrent update(), Executor pool double-construction on
concurrent first submit(), WorkQueue.remove_consumer() dropping the wrong
handler, and reaper-driven requeue starving push-only consumers. Each test
(other than the general exactly-once stress test, which is a regression
guard rather than a reproduction of a specific defect) is written to FAIL
against the pre-fix code and PASS after it.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from eventforge import ExecutionMode, Executor, Meter
from eventforge.types import TaskStatus
from eventforge.work_queue import WorkQueue

# =============================================================================
# WorkQueue: N producers x M consumers, exactly-once delivery
# =============================================================================


class TestWorkQueueProducerConsumerExactlyOnce:
    def test_n_producers_m_consumers_exactly_once(self):
        wq = WorkQueue(max_retries=5)
        n_producers = 4
        n_consumers = 3
        per_producer = 200
        total = n_producers * per_producer

        delivered: list[int] = []
        lock = threading.Lock()

        def make_handler() -> Callable:
            def handler(msg):
                with lock:
                    delivered.append(msg.payload)
                wq.ack(msg.headers["_wq_delivery_id"])

            return handler

        for _ in range(n_consumers):
            wq.consume("work", make_handler())

        def producer(base: int) -> None:
            for i in range(per_producer):
                wq.enqueue("work", base * per_producer + i)

        threads = [
            threading.Thread(target=producer, args=(p,)) for p in range(n_producers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            with lock:
                if len(delivered) >= total:
                    break
            time.sleep(0.02)

        wq.close()

        with lock:
            got = list(delivered)

        assert len(got) == total, f"expected {total} deliveries, got {len(got)}"
        assert len(set(got)) == total, "duplicate delivery detected"
        assert set(got) == set(range(total))

    def test_failures_result_in_exactly_one_ack_or_dead_letter_per_message(self):
        wq = WorkQueue(max_retries=3, default_visibility_timeout=5.0)
        total = 60
        acked: list[int] = []
        lock = threading.Lock()

        def flaky_handler(msg):
            # Deterministically fail every other delivery attempt so
            # messages route through nack -> retry at least once each.
            if msg.headers.get("_wq_retry_count", 0) % 2 == 0:
                raise RuntimeError("simulated failure")
            with lock:
                acked.append(msg.payload)
            wq.ack(msg.headers["_wq_delivery_id"])

        wq.consume("flaky", flaky_handler)

        for i in range(total):
            wq.enqueue("flaky", i)

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            pending = wq.pending_count("flaky")
            in_flight = wq.in_flight_count("flaky")
            dl = wq.pending_count("flaky.dead_letter")
            with lock:
                done = len(acked)
            if pending == 0 and in_flight == 0 and (done + dl) >= total:
                break
            time.sleep(0.02)

        dead_letter_count = wq.pending_count("flaky.dead_letter")
        wq.close()

        with lock:
            got = list(acked)

        assert len(got) == len(set(got)), "a message was acked more than once"
        assert len(got) + dead_letter_count == total, (
            f"acked={len(got)} dead_letter={dead_letter_count} total={total} "
            "-- messages lost or double-counted"
        )


# =============================================================================
# WorkQueue.remove_consumer: must remove the exact handler, not "last in list"
# =============================================================================


class TestRemoveConsumerCorrectness:
    def test_remove_one_consumer_does_not_drop_another(self):
        wq = WorkQueue()
        received_a: list = []
        received_b: list = []
        lock = threading.Lock()

        def handler_a(msg):
            with lock:
                received_a.append(msg)

        def handler_b(msg):
            with lock:
                received_b.append(msg)

        # Deterministic registration order: a first, b second. A "pop the
        # last handler in the list" implementation removes b's handler when
        # asked to remove a -- this reproduces that bug regardless of
        # timing, then the removal itself races against live dispatch.
        id_a = wq.consume("topic", handler_a, consumer_group="group")
        wq.consume("topic", handler_b, consumer_group="group")

        assert wq.remove_consumer(id_a) is True

        def producer() -> None:
            for i in range(20):
                wq.enqueue("topic", i)

        threads = [threading.Thread(target=producer) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            with lock:
                if len(received_b) >= 40:
                    break
            time.sleep(0.02)

        wq.close()

        with lock:
            a_count, b_count = len(received_a), len(received_b)

        assert a_count == 0, "removed consumer A must not receive any messages"
        assert b_count == 40, (
            "consumer B's handler must stay registered after A is removed"
        )


# =============================================================================
# WorkQueue reaper: timeout-driven requeue must reach push-only consumers
# =============================================================================


class TestReaperRequeueDispatch:
    def test_reaper_requeue_redelivers_to_push_consumer_without_new_enqueue(self):
        wq = WorkQueue(
            default_visibility_timeout=0.15, reaper_interval=0.1, max_retries=5
        )
        deliveries: list[int] = []
        lock = threading.Lock()

        def handler(msg):
            with lock:
                deliveries.append(msg.headers.get("_wq_retry_count", 0))
            # Never ack -- forces a visibility-timeout requeue on every
            # delivery, with no further enqueue()/consume() call on this
            # topic to otherwise trigger dispatch.

        wq.consume("starve", handler)
        wq.enqueue("starve", "payload")

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            with lock:
                if len(deliveries) >= 2:
                    break
            time.sleep(0.05)

        with lock:
            count = len(deliveries)
        wq.close()

        assert count >= 2, (
            f"expected reaper-driven redelivery to a push consumer, got {count} "
            "deliveries total -- reaper requeue must call _try_dispatch(topic)"
        )


# =============================================================================
# Meter: concurrent update() must not lose counts
# =============================================================================


class _SlowAttrMeter(Meter):
    """Widens update()'s read-modify-write window without changing what
    gets stored.

    CPython's specializing interpreter (3.11+) only checks for a GIL
    hand-off at loop back-edges and calls; a straight-line attribute
    read-modify-write with no call in between (exactly what pre-fix
    ``Meter.update()`` was) tends to run to completion within one GIL
    quantum in practice, so a plain threaded stress loop rarely observes
    the race even though the code has no synchronization. Injecting a
    trivial delay on each of the aggregator's attribute stores (via
    ``__setattr__``, which every ``self.x = ...`` in ``update()`` already
    goes through) forces a real preemption point at exactly the vulnerable
    spot, making the underlying race deterministically observable. The
    locked (fixed) implementation stays correct despite the added delay
    because the whole ``update()`` body runs inside ``_state_lock``.
    """

    _SLOW_ATTRS = {"last", "sum", "count", "max_val", "min_val"}

    def __setattr__(self, name: str, value) -> None:
        if name in self._SLOW_ATTRS:
            time.sleep(0.001)
        object.__setattr__(self, name, value)


class TestMeterConcurrentUpdate:
    def test_concurrent_update_no_lost_counts(self):
        meter = _SlowAttrMeter(name="counter", reduction="sum")
        n_threads = 8
        n_updates = 20
        barrier = threading.Barrier(n_threads)

        def worker() -> None:
            barrier.wait()
            for _ in range(n_updates):
                meter.update(1.0)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = n_threads * n_updates
        assert meter.count == expected, f"lost updates: {meter.count} != {expected}"
        assert meter.sum == float(expected)


# =============================================================================
# Executor: concurrent first submit() must not double-construct the pool
# =============================================================================


def _compute(n: int) -> int:
    return sum(range(n))


class _CountingThreadPoolExecutor(ThreadPoolExecutor):
    """Counts constructions and adds a small delay in __init__.

    The delay widens the window between the unlocked "if not running"
    check in ``submit()``/``start()`` and the pool actually being assigned
    -- without it, 20 threads racing through a few bytecodes of Python
    tends not to interleave inside that specific window often enough to
    reliably reproduce the bug in a plain stress loop, even though the
    check-then-act is genuinely unsynchronized pre-fix.
    """

    instances = 0

    def __init__(self, *args, **kwargs) -> None:
        _CountingThreadPoolExecutor.instances += 1
        time.sleep(0.01)
        super().__init__(*args, **kwargs)


class TestExecutorStartRace:
    def test_concurrent_submit_constructs_pool_once(self, monkeypatch):
        import eventforge.executor as executor_mod

        monkeypatch.setattr(
            executor_mod, "ThreadPoolExecutor", _CountingThreadPoolExecutor
        )
        _CountingThreadPoolExecutor.instances = 0

        ex = Executor(mode=ExecutionMode.THREAD, max_workers=4)
        n = 20
        barrier = threading.Barrier(n)
        task_ids: list = [None] * n

        def submitter(i: int) -> None:
            barrier.wait()
            task_ids[i] = ex.submit(_compute, 100)

        threads = [threading.Thread(target=submitter, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        results = [ex.result(tid, timeout=5.0) for tid in task_ids]
        ex.stop()

        assert all(r.status == TaskStatus.COMPLETED for r in results)
        assert _CountingThreadPoolExecutor.instances == 1, (
            f"expected exactly one pool construction, got "
            f"{_CountingThreadPoolExecutor.instances}"
        )
