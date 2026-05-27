"""Tests for NatsTransport.

Requires a running NATS server at nats://localhost:4222; otherwise the whole
module is skipped cleanly (e.g. in CI without a server).
"""

import time

import pytest

pytest.importorskip("nats")

from eventforge.transports.nats import NatsTransport  # noqa: E402
from eventforge.types import Message  # noqa: E402


def _poll(predicate, timeout=2.0, interval=0.01):
    deadline = time.time() + timeout
    value = predicate()
    while not value and time.time() < deadline:
        time.sleep(interval)
        value = predicate()
    return value


@pytest.fixture(scope="module")
def transport():
    # Connect once for the whole module; fail fast (short connect_timeout) and
    # skip cleanly when no server is reachable (e.g. CI without a NATS server).
    try:
        t = NatsTransport(servers="nats://localhost:4222", connect_timeout=0.5)
    except Exception as exc:  # no server reachable
        pytest.skip(f"No NATS server at nats://localhost:4222: {exc}")
    yield t
    t.close()


class TestNatsTransport:
    def test_send_subscribe_receive_round_trip(self, transport):
        received = []
        transport.subscribe("test.subject", received.append)
        time.sleep(0.1)

        transport.send(Message(topic="test.subject", payload="hello-nats"))

        assert _poll(lambda: len(received) == 1)
        assert received[0].payload == "hello-nats"

    def test_receive_returns_message(self, transport):
        transport.receive("rx.subject", timeout=0.01)  # warm up subscription
        time.sleep(0.1)
        transport.send(Message(topic="rx.subject", payload="via-queue"))

        msg = transport.receive("rx.subject", timeout=2.0)
        assert msg is not None
        assert msg.payload == "via-queue"

    def test_unsubscribe_stops_delivery(self, transport):
        received = []
        sub_id = transport.subscribe("u.subject", received.append)
        time.sleep(0.1)

        transport.send(Message(topic="u.subject", payload="before"))
        assert _poll(lambda: len(received) == 1)

        assert transport.unsubscribe(sub_id) is True
        time.sleep(0.1)
        transport.send(Message(topic="u.subject", payload="after"))
        time.sleep(0.3)

        assert len(received) == 1
