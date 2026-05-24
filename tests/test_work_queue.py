"""Tests for WorkQueue: competing consumers, ack/nack, dead-letter, visibility timeout."""

import threading
import time

import pytest

from eventforge.work_queue import InFlightEntry, QueueFullError, WorkQueue

# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


class TestWorkQueueEnqueue:
    def test_enqueue_returns_message_id(self):
        wq = WorkQueue()
        msg_id = wq.enqueue("tasks", "hello")
        assert isinstance(msg_id, str)
        assert len(msg_id) > 0
        wq.close()

    def test_enqueue_with_user_headers(self):
        wq = WorkQueue()
        wq.enqueue("tasks", "hello", priority=5, source="test")
        msg = wq.dequeue("tasks", timeout=1.0)
        assert msg is not None
        assert msg.headers["priority"] == 5
        assert msg.headers["source"] == "test"
        # internal headers also present
        assert msg.headers["_wq_retry_count"] == 0
        assert msg.headers["_wq_original_topic"] == "tasks"
        wq.close()

    def test_enqueue_backpressure_raises(self):
        wq = WorkQueue(max_work_queue_size=2)
        wq.enqueue("tasks", "a")
        wq.enqueue("tasks", "b")
        with pytest.raises(QueueFullError):
            wq.enqueue("tasks", "c")
        wq.close()

    def test_enqueue_unlimited_queue(self):
        wq = WorkQueue(max_work_queue_size=0)
        for i in range(100):
            wq.enqueue("tasks", i)
        assert wq.pending_count("tasks") == 100
        wq.close()


# ---------------------------------------------------------------------------
# Dequeue
# ---------------------------------------------------------------------------


class TestWorkQueueDequeue:
    def test_dequeue_returns_message(self):
        wq = WorkQueue()
        wq.enqueue("tasks", "hello")
        msg = wq.dequeue("tasks", timeout=1.0)
        assert msg is not None
        assert msg.payload == "hello"
        wq.close()

    def test_dequeue_fifo_order(self):
        wq = WorkQueue()
        for val in ["a", "b", "c"]:
            wq.enqueue("tasks", val)
        results = []
        for _ in range(3):
            msg = wq.dequeue("tasks", timeout=1.0)
            assert msg is not None
            results.append(msg.payload)
        assert results == ["a", "b", "c"]
        wq.close()

    def test_dequeue_timeout_returns_none(self):
        wq = WorkQueue()
        msg = wq.dequeue("tasks", timeout=0.1)
        assert msg is None
        wq.close()

    def test_dequeue_blocks_until_message(self):
        wq = WorkQueue()
        result = []

        def consumer():
            msg = wq.dequeue("tasks", timeout=5.0)
            if msg:
                result.append(msg.payload)

        t = threading.Thread(target=consumer)
        t.start()
        time.sleep(0.1)
        wq.enqueue("tasks", "delayed")
        t.join(timeout=5.0)
        assert result == ["delayed"]
        wq.close()

    def test_dequeue_sets_delivery_id_header(self):
        wq = WorkQueue()
        wq.enqueue("tasks", "hello")
        msg = wq.dequeue("tasks", timeout=1.0)
        assert msg is not None
        assert "_wq_delivery_id" in msg.headers
        assert isinstance(msg.headers["_wq_delivery_id"], str)
        wq.close()

    def test_dequeue_message_becomes_in_flight(self):
        wq = WorkQueue()
        wq.enqueue("tasks", "hello")
        assert wq.in_flight_count() == 0
        msg = wq.dequeue("tasks", timeout=1.0)
        assert wq.in_flight_count() == 1
        assert wq.pending_count("tasks") == 0
        wq.close()


# ---------------------------------------------------------------------------
# Ack
# ---------------------------------------------------------------------------


class TestWorkQueueAck:
    def test_ack_removes_from_in_flight(self):
        wq = WorkQueue()
        wq.enqueue("tasks", "hello")
        msg = wq.dequeue("tasks", timeout=1.0)
        delivery_id = msg.headers["_wq_delivery_id"]
        assert wq.in_flight_count() == 1
        assert wq.ack(delivery_id) is True
        assert wq.in_flight_count() == 0
        wq.close()

    def test_ack_unknown_delivery_id_returns_false(self):
        wq = WorkQueue()
        assert wq.ack("nonexistent") is False
        wq.close()

    def test_ack_same_delivery_twice_returns_false(self):
        wq = WorkQueue()
        wq.enqueue("tasks", "hello")
        msg = wq.dequeue("tasks", timeout=1.0)
        delivery_id = msg.headers["_wq_delivery_id"]
        assert wq.ack(delivery_id) is True
        assert wq.ack(delivery_id) is False
        wq.close()


# ---------------------------------------------------------------------------
# Nack
# ---------------------------------------------------------------------------


class TestWorkQueueNack:
    def test_nack_requeue_puts_message_back(self):
        wq = WorkQueue(max_retries=5)
        wq.enqueue("tasks", "retry_me")
        msg = wq.dequeue("tasks", timeout=1.0)
        delivery_id = msg.headers["_wq_delivery_id"]
        assert wq.nack(delivery_id, requeue=True) is True
        assert wq.pending_count("tasks") == 1
        # dequeue again — same payload
        msg2 = wq.dequeue("tasks", timeout=1.0)
        assert msg2.payload == "retry_me"
        wq.close()

    def test_nack_no_requeue_dead_letters(self):
        wq = WorkQueue()
        wq.enqueue("tasks", "dead")
        msg = wq.dequeue("tasks", timeout=1.0)
        delivery_id = msg.headers["_wq_delivery_id"]
        wq.nack(delivery_id, requeue=False)
        # should be in dead letter topic
        dl = wq.dequeue("tasks.dead_letter", timeout=1.0)
        assert dl is not None
        assert dl.payload == "dead"
        assert dl.headers["_wq_dead_letter_reason"] == "nack_no_requeue"
        wq.close()

    def test_nack_max_retries_dead_letters(self):
        wq = WorkQueue(max_retries=2)
        wq.enqueue("tasks", "poison")
        # First delivery + nack (retry_count goes 0 -> 1)
        msg = wq.dequeue("tasks", timeout=1.0)
        wq.nack(msg.headers["_wq_delivery_id"], requeue=True)
        # Second delivery + nack (retry_count goes 1 -> 2, which == max_retries)
        msg = wq.dequeue("tasks", timeout=1.0)
        wq.nack(msg.headers["_wq_delivery_id"], requeue=True)
        # Should be dead-lettered now, not requeued
        assert wq.pending_count("tasks") == 0
        dl = wq.dequeue("tasks.dead_letter", timeout=1.0)
        assert dl is not None
        assert dl.payload == "poison"
        assert dl.headers["_wq_dead_letter_reason"] == "max_retries_exceeded"
        wq.close()

    def test_nack_increments_retry_count_header(self):
        wq = WorkQueue(max_retries=5)
        wq.enqueue("tasks", "val")
        msg = wq.dequeue("tasks", timeout=1.0)
        assert msg.headers["_wq_retry_count"] == 0
        wq.nack(msg.headers["_wq_delivery_id"], requeue=True)
        msg2 = wq.dequeue("tasks", timeout=1.0)
        assert msg2.headers["_wq_retry_count"] == 1
        wq.close()

    def test_nack_unknown_delivery_id_returns_false(self):
        wq = WorkQueue()
        assert wq.nack("nonexistent") is False
        wq.close()


# ---------------------------------------------------------------------------
# Dead Letter
# ---------------------------------------------------------------------------


class TestWorkQueueDeadLetter:
    def test_dead_letter_topic_name(self):
        wq = WorkQueue()
        wq.enqueue("jobs", "fail")
        msg = wq.dequeue("jobs", timeout=1.0)
        wq.nack(msg.headers["_wq_delivery_id"], requeue=False)
        dl = wq.dequeue("jobs.dead_letter", timeout=1.0)
        assert dl is not None
        assert dl.topic == "jobs.dead_letter"
        wq.close()

    def test_dead_letter_preserves_payload(self):
        wq = WorkQueue()
        wq.enqueue("jobs", {"key": "value"})
        msg = wq.dequeue("jobs", timeout=1.0)
        wq.nack(msg.headers["_wq_delivery_id"], requeue=False)
        dl = wq.dequeue("jobs.dead_letter", timeout=1.0)
        assert dl.payload == {"key": "value"}
        wq.close()

    def test_dead_letter_headers_enriched(self):
        wq = WorkQueue()
        wq.enqueue("jobs", "fail")
        msg = wq.dequeue("jobs", timeout=1.0)
        wq.nack(msg.headers["_wq_delivery_id"], requeue=False)
        dl = wq.dequeue("jobs.dead_letter", timeout=1.0)
        assert "_wq_dead_lettered_at" in dl.headers
        assert "_wq_dead_letter_reason" in dl.headers
        assert dl.headers["_wq_original_topic"] == "jobs"
        wq.close()

    def test_dead_letter_consumable_via_dequeue(self):
        wq = WorkQueue()
        wq.enqueue("jobs", "fail")
        msg = wq.dequeue("jobs", timeout=1.0)
        wq.nack(msg.headers["_wq_delivery_id"], requeue=False)
        # Can dequeue and ack from dead letter topic
        dl = wq.dequeue("jobs.dead_letter", timeout=1.0)
        assert dl is not None
        dl_delivery = dl.headers["_wq_delivery_id"]
        assert wq.ack(dl_delivery) is True
        wq.close()


# ---------------------------------------------------------------------------
# Competing Consumers (push-based)
# ---------------------------------------------------------------------------


class TestWorkQueueCompetingConsumers:
    def test_consume_single_consumer(self):
        wq = WorkQueue()
        received = []
        wq.consume("tasks", lambda m: received.append(m.payload))
        wq.enqueue("tasks", "a")
        wq.enqueue("tasks", "b")
        time.sleep(0.2)
        assert sorted(received) == ["a", "b"]
        wq.close()

    def test_consume_round_robin(self):
        wq = WorkQueue()
        consumer_a = []
        consumer_b = []
        wq.consume("tasks", lambda m: consumer_a.append(m.payload), consumer_group="g1")
        wq.consume("tasks", lambda m: consumer_b.append(m.payload), consumer_group="g1")
        for i in range(4):
            wq.enqueue("tasks", i)
        time.sleep(0.3)
        # Each consumer should get 2 messages
        assert len(consumer_a) == 2
        assert len(consumer_b) == 2
        # All messages accounted for
        assert sorted(consumer_a + consumer_b) == [0, 1, 2, 3]
        wq.close()

    def test_consume_different_groups_get_copies(self):
        wq = WorkQueue()
        group_a = []
        group_b = []
        wq.consume("tasks", lambda m: group_a.append(m.payload), consumer_group="ga")
        wq.consume("tasks", lambda m: group_b.append(m.payload), consumer_group="gb")
        wq.enqueue("tasks", "msg")
        time.sleep(0.2)
        # Each group gets its own copy
        assert group_a == ["msg"]
        assert group_b == ["msg"]
        wq.close()

    def test_consume_handler_exception_auto_nacks(self):
        wq = WorkQueue(max_retries=5)
        call_count = []

        def flaky_handler(msg):
            call_count.append(1)
            if len(call_count) == 1:
                raise ValueError("fail first time")

        wq.consume("tasks", flaky_handler)
        wq.enqueue("tasks", "retry_me")
        time.sleep(0.5)
        # Should have been called at least twice (first fails, requeued, second succeeds)
        assert len(call_count) >= 2
        wq.close()

    def test_remove_consumer(self):
        wq = WorkQueue()
        received = []
        cid = wq.consume("tasks", lambda m: received.append(m.payload))
        assert wq.remove_consumer(cid) is True
        wq.enqueue("tasks", "orphan")
        time.sleep(0.1)
        # No consumer left — message stays pending
        assert received == []
        assert wq.pending_count("tasks") == 1
        wq.close()


# ---------------------------------------------------------------------------
# Visibility Timeout
# ---------------------------------------------------------------------------


class TestWorkQueueVisibilityTimeout:
    def test_visibility_timeout_requeues(self):
        wq = WorkQueue(
            default_visibility_timeout=0.2,
            max_retries=5,
            reaper_interval=0.1,
        )
        wq.enqueue("tasks", "expire_me")
        msg = wq.dequeue("tasks", timeout=1.0)
        assert msg is not None
        # Don't ack — wait for visibility timeout
        time.sleep(0.5)
        # Message should be requeued
        msg2 = wq.dequeue("tasks", timeout=1.0)
        assert msg2 is not None
        assert msg2.payload == "expire_me"
        assert msg2.headers["_wq_retry_count"] == 1
        wq.ack(msg2.headers["_wq_delivery_id"])
        wq.close()

    def test_visibility_timeout_dead_letters_after_max_retries(self):
        wq = WorkQueue(
            default_visibility_timeout=0.15,
            max_retries=2,
            reaper_interval=0.1,
        )
        wq.enqueue("tasks", "doomed")
        # Let it expire twice (retry_count 0->1, 1->2 which hits max)
        msg = wq.dequeue("tasks", timeout=1.0)
        time.sleep(0.4)  # expires, retry_count becomes 1
        msg = wq.dequeue("tasks", timeout=1.0)
        assert msg is not None
        time.sleep(
            0.4
        )  # expires again, retry_count becomes 2 == max_retries -> dead letter
        # Should be in dead letter now
        dl = wq.dequeue("tasks.dead_letter", timeout=1.0)
        assert dl is not None
        assert dl.payload == "doomed"
        assert dl.headers["_wq_dead_letter_reason"] == "visibility_timeout_exceeded"
        wq.close()

    def test_ack_before_timeout_prevents_requeue(self):
        wq = WorkQueue(
            default_visibility_timeout=0.5,
            max_retries=5,
            reaper_interval=0.1,
        )
        wq.enqueue("tasks", "fast")
        msg = wq.dequeue("tasks", timeout=1.0)
        wq.ack(msg.headers["_wq_delivery_id"])
        time.sleep(0.8)
        # Nothing should be requeued
        msg2 = wq.dequeue("tasks", timeout=0.1)
        assert msg2 is None
        wq.close()


# ---------------------------------------------------------------------------
# Pub/Sub Coexistence
# ---------------------------------------------------------------------------


class TestWorkQueuePubSubCoexistence:
    def test_parent_publish_subscribe_still_works(self):
        wq = WorkQueue()
        received = []
        wq.subscribe("events", lambda m: received.append(m.payload))
        wq.publish("events", "pubsub_msg")
        time.sleep(0.1)
        assert received == ["pubsub_msg"]
        wq.close()

    def test_enqueue_does_not_fan_out_to_subscribers(self):
        wq = WorkQueue()
        received = []
        wq.subscribe("tasks", lambda m: received.append(m.payload))
        wq.enqueue("tasks", "work_msg")
        time.sleep(0.1)
        # pub/sub subscriber should NOT receive work queue messages
        assert received == []
        wq.close()

    def test_publish_does_not_enter_work_queue(self):
        wq = WorkQueue()
        wq.publish("tasks", "pubsub_msg")
        # dequeue should not find it
        msg = wq.dequeue("tasks", timeout=0.1)
        assert msg is None
        wq.close()


# ---------------------------------------------------------------------------
# Thread Safety
# ---------------------------------------------------------------------------


class TestWorkQueueThreadSafety:
    def test_concurrent_enqueue_dequeue(self):
        wq = WorkQueue()
        n = 50
        results = []

        def producer():
            for i in range(n):
                wq.enqueue("tasks", i)

        def consumer():
            for _ in range(n):
                msg = wq.dequeue("tasks", timeout=5.0)
                if msg:
                    results.append(msg.payload)
                    wq.ack(msg.headers["_wq_delivery_id"])

        t_prod = threading.Thread(target=producer)
        t_cons = threading.Thread(target=consumer)
        t_cons.start()
        t_prod.start()
        t_prod.join(timeout=10.0)
        t_cons.join(timeout=10.0)
        assert sorted(results) == list(range(n))
        wq.close()

    def test_concurrent_ack_nack(self):
        wq = WorkQueue(max_retries=10)
        n = 20
        for i in range(n):
            wq.enqueue("tasks", i)

        delivery_ids = []
        for _ in range(n):
            msg = wq.dequeue("tasks", timeout=1.0)
            assert msg is not None
            delivery_ids.append(msg.headers["_wq_delivery_id"])

        # Ack half, nack half from different threads
        errors = []

        def ack_half():
            try:
                for did in delivery_ids[: n // 2]:
                    wq.ack(did)
            except Exception as e:
                errors.append(e)

        def nack_half():
            try:
                for did in delivery_ids[n // 2 :]:
                    wq.nack(did, requeue=True)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=ack_half)
        t2 = threading.Thread(target=nack_half)
        t1.start()
        t2.start()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)
        assert errors == []
        # Nack'd messages should be back in pending
        assert wq.pending_count("tasks") == n // 2
        wq.close()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestWorkQueueLifecycle:
    def test_context_manager(self):
        with WorkQueue() as wq:
            wq.enqueue("tasks", "hello")
            msg = wq.dequeue("tasks", timeout=1.0)
            assert msg.payload == "hello"

    def test_close_stops_reaper(self):
        wq = WorkQueue(reaper_interval=0.1)
        wq.enqueue("tasks", "x")
        wq.dequeue("tasks", timeout=1.0)  # starts reaper
        assert wq._reaper_thread is not None
        assert wq._reaper_thread.is_alive()
        wq.close()
        assert wq._reaper_thread is None or not wq._reaper_thread.is_alive()

    def test_close_unblocks_dequeue(self):
        wq = WorkQueue()
        result = [None]

        def blocked_consumer():
            result[0] = wq.dequeue("tasks", timeout=10.0)

        t = threading.Thread(target=blocked_consumer)
        t.start()
        time.sleep(0.1)
        wq.close()
        t.join(timeout=3.0)
        assert result[0] is None
        assert not t.is_alive()

    def test_pending_count(self):
        wq = WorkQueue()
        wq.enqueue("tasks", "a")
        wq.enqueue("tasks", "b")
        wq.enqueue("tasks", "c")
        assert wq.pending_count("tasks") == 3
        wq.dequeue("tasks", timeout=1.0)
        assert wq.pending_count("tasks") == 2
        wq.close()

    def test_in_flight_count(self):
        wq = WorkQueue()
        wq.enqueue("tasks", "a")
        wq.enqueue("tasks", "b")
        msg1 = wq.dequeue("tasks", timeout=1.0)
        msg2 = wq.dequeue("tasks", timeout=1.0)
        assert wq.in_flight_count() == 2
        assert wq.in_flight_count("tasks") == 1 or wq.in_flight_count("tasks") == 2
        wq.ack(msg1.headers["_wq_delivery_id"])
        assert wq.in_flight_count() == 1
        wq.close()

    def test_in_flight_count_by_topic(self):
        wq = WorkQueue()
        wq.enqueue("a", "x")
        wq.enqueue("b", "y")
        wq.dequeue("a", timeout=1.0)
        wq.dequeue("b", timeout=1.0)
        assert wq.in_flight_count("a") == 1
        assert wq.in_flight_count("b") == 1
        assert wq.in_flight_count() == 2
        wq.close()
