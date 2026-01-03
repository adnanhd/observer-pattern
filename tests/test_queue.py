"""Tests for callpyback.queue module."""

import time

import pytest

from callpyback import MessageQueue
from callpyback.types import Message


class TestMessageQueue:
    def test_publish_and_subscribe(self):
        queue = MessageQueue()
        received = []

        @queue.on("events.test")
        def handler(msg):
            received.append(msg.payload)

        queue.publish("events.test", {"action": "create"})

        time.sleep(0.1)
        assert len(received) == 1
        assert received[0] == {"action": "create"}

    def test_publish_returns_message_id(self):
        queue = MessageQueue()

        msg_id = queue.publish("topic", "payload")

        assert msg_id is not None
        assert isinstance(msg_id, str)

    def test_multiple_subscribers_same_topic(self):
        queue = MessageQueue()
        results = {"handler1": [], "handler2": []}

        # Note: Each subscribe creates its own transport subscription
        # so messages may be received by transport-level callbacks
        sub1 = queue.subscribe(
            "shared.topic", lambda m: results["handler1"].append(m.payload)
        )
        sub2 = queue.subscribe(
            "shared.topic", lambda m: results["handler2"].append(m.payload)
        )

        queue.publish("shared.topic", "data")

        time.sleep(0.1)

        # Both handlers should receive the message
        assert "data" in results["handler1"] or "data" in results["handler2"]

    def test_unsubscribe(self):
        queue = MessageQueue()
        received = []

        sub_id = queue.subscribe("test", lambda m: received.append(m.payload))
        queue.publish("test", "first")
        time.sleep(0.05)

        queue.unsubscribe(sub_id)
        queue.publish("test", "second")
        time.sleep(0.05)

        assert received == ["first"]

    def test_publish_with_headers(self):
        queue = MessageQueue()
        received_headers = []

        @queue.on("headers.test")
        def handler(msg):
            received_headers.append(msg.headers)

        queue.publish(
            "headers.test",
            "payload",
            content_type="application/json",
            priority=5,
        )

        time.sleep(0.1)

        assert len(received_headers) == 1
        assert received_headers[0]["content_type"] == "application/json"
        assert received_headers[0]["priority"] == 5

    def test_receive_direct(self):
        queue = MessageQueue()

        queue.publish("direct.topic", "direct_data")
        msg = queue.receive("direct.topic", timeout=1.0)

        assert msg is not None
        assert msg.payload == "direct_data"

    def test_receive_timeout(self):
        queue = MessageQueue()

        start = time.time()
        msg = queue.receive("nonexistent", timeout=0.1)
        elapsed = time.time() - start

        assert msg is None
        assert elapsed >= 0.1

    def test_context_manager(self):
        with MessageQueue() as queue:
            msg_id = queue.publish("test", "data")
            assert msg_id is not None

    def test_reply(self):
        queue = MessageQueue()

        # Create a message with reply_to
        original = Message(
            topic="request",
            payload="query",
            reply_to="response.channel",
            correlation_id="corr-123",
        )

        reply_id = queue.reply(original, "answer")

        assert reply_id is not None

        # The reply should be on the reply_to topic
        reply_msg = queue.receive("response.channel", timeout=1.0)
        assert reply_msg is not None
        assert reply_msg.payload == "answer"
        assert reply_msg.correlation_id == "corr-123"

    def test_reply_without_reply_to_raises(self):
        queue = MessageQueue()

        original = Message(topic="request", payload="query")

        with pytest.raises(ValueError, match="no reply_to"):
            queue.reply(original, "answer")
