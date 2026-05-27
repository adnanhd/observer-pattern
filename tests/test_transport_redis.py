"""Tests for RedisTransport using fakeredis (no real server needed)."""

import time

import pytest

fakeredis = pytest.importorskip("fakeredis")

from eventforge.transports.redis import RedisTransport  # noqa: E402
from eventforge.types import Message  # noqa: E402


def _poll(predicate, timeout=2.0, interval=0.01):
    """Poll predicate until truthy or timeout; returns its last value."""
    deadline = time.time() + timeout
    value = predicate()
    while not value and time.time() < deadline:
        time.sleep(interval)
        value = predicate()
    return value


@pytest.fixture
def transport():
    client = fakeredis.FakeStrictRedis()
    t = RedisTransport(client=client)
    yield t
    t.close()


class TestRedisTransport:
    def test_send_and_subscribe_callback(self, transport):
        received = []
        transport.subscribe("test.channel", received.append)

        # Give the listener a moment to register the psubscribe.
        time.sleep(0.05)
        transport.send(Message(topic="test.channel", payload="hello"))

        assert _poll(lambda: len(received) == 1)
        assert received[0].payload == "hello"
        assert received[0].topic == "test.channel"

    def test_receive_returns_message(self, transport):
        # receive() auto-ensures a subscription exists for the topic.
        transport.receive("rx.topic", timeout=0.01)  # warm up subscription
        time.sleep(0.05)
        transport.send(Message(topic="rx.topic", payload="payload-1"))

        msg = transport.receive("rx.topic", timeout=2.0)
        assert msg is not None
        assert msg.payload == "payload-1"

    def test_wildcard_subscription_matches(self, transport):
        received = []
        transport.subscribe("events.*", received.append)
        time.sleep(0.05)

        transport.send(Message(topic="events.created", payload="c"))
        transport.send(Message(topic="events.deleted", payload="d"))

        assert _poll(lambda: len(received) == 2)
        payloads = sorted(m.payload for m in received)
        assert payloads == ["c", "d"]

    def test_wildcard_double_star_matches_segments(self, transport):
        received = []
        transport.subscribe("events.**", received.append)
        time.sleep(0.05)

        transport.send(Message(topic="events.user.created", payload="deep"))

        assert _poll(lambda: len(received) == 1)
        assert received[0].payload == "deep"

    def test_single_star_does_not_cross_segment(self, transport):
        received = []
        transport.subscribe("events.*", received.append)
        time.sleep(0.05)

        # Single * is segment-local: "events.user.created" must NOT match.
        transport.send(Message(topic="events.user.created", payload="nope"))
        transport.send(Message(topic="events.ok", payload="yes"))

        assert _poll(lambda: len(received) == 1)
        assert received[0].payload == "yes"

    def test_unsubscribe_stops_delivery(self, transport):
        received = []
        sub_id = transport.subscribe("stop.me", received.append)
        time.sleep(0.05)

        transport.send(Message(topic="stop.me", payload="before"))
        assert _poll(lambda: len(received) == 1)

        assert transport.unsubscribe(sub_id) is True
        time.sleep(0.05)
        transport.send(Message(topic="stop.me", payload="after"))
        time.sleep(0.2)

        assert len(received) == 1
        assert received[0].payload == "before"

    def test_unsubscribe_unknown_returns_false(self, transport):
        assert transport.unsubscribe("does-not-exist") is False

    def test_close_is_clean(self):
        client = fakeredis.FakeStrictRedis()
        t = RedisTransport(client=client)
        t.subscribe("x", lambda m: None)
        t.send(Message(topic="x", payload="v"))
        t.close()
        # After close, send raises and receive returns None.
        with pytest.raises(RuntimeError):
            t.send(Message(topic="x", payload="v2"))
        assert t.receive("x", timeout=0.05) is None
