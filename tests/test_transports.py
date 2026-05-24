"""Tests for eventforge.transports module."""

import threading
import time

import pytest

from eventforge.transports import MemoryTransport
from eventforge.types import Message


class TestMemoryTransport:
    def test_send_and_receive(self):
        transport = MemoryTransport()
        msg = Message(topic="test.channel", payload="hello")

        transport.send(msg)
        received = transport.receive("test.channel", timeout=1.0)

        assert received is not None
        assert received.payload == "hello"

    def test_receive_timeout(self):
        transport = MemoryTransport()

        start = time.time()
        received = transport.receive("empty.channel", timeout=0.1)
        elapsed = time.time() - start

        assert received is None
        assert elapsed >= 0.1

    def test_subscribe_callback(self):
        transport = MemoryTransport()
        received_messages = []

        def callback(msg):
            received_messages.append(msg)

        sub_id = transport.subscribe("notifications", callback)

        transport.send(Message(topic="notifications", payload="alert1"))

        time.sleep(0.1)  # Allow callbacks to process

        assert len(received_messages) == 1
        assert received_messages[0].payload == "alert1"

        transport.unsubscribe(sub_id)

    def test_unsubscribe(self):
        transport = MemoryTransport()
        received_messages = []

        def callback(msg):
            received_messages.append(msg)

        sub_id = transport.subscribe("test", callback)
        transport.send(Message(topic="test", payload="before"))
        time.sleep(0.05)

        transport.unsubscribe(sub_id)
        transport.send(Message(topic="test", payload="after"))
        time.sleep(0.05)

        assert len(received_messages) == 1
        assert received_messages[0].payload == "before"

    def test_close_prevents_send(self):
        transport = MemoryTransport()

        transport.close()

        with pytest.raises(RuntimeError):
            transport.send(Message(topic="test", payload="ignored"))

    def test_close_returns_none_on_receive(self):
        transport = MemoryTransport()
        transport.close()

        result = transport.receive("test", timeout=0.1)
        assert result is None

    def test_thread_safety(self):
        transport = MemoryTransport()
        received = []
        lock = threading.Lock()

        def sender():
            for i in range(100):
                transport.send(Message(topic="concurrent", payload=i))

        def receiver():
            for _ in range(100):
                msg = transport.receive("concurrent", timeout=1.0)
                if msg:
                    with lock:
                        received.append(msg.payload)

        threads = [
            threading.Thread(target=sender),
            threading.Thread(target=receiver),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(received) == 100

    def test_multiple_topics(self):
        transport = MemoryTransport()

        transport.send(Message(topic="topic1", payload="data1"))
        transport.send(Message(topic="topic2", payload="data2"))

        msg1 = transport.receive("topic1", timeout=1.0)
        msg2 = transport.receive("topic2", timeout=1.0)

        assert msg1.payload == "data1"
        assert msg2.payload == "data2"

    def test_fifo_order(self):
        transport = MemoryTransport()

        for i in range(5):
            transport.send(Message(topic="ordered", payload=i))

        received = []
        for _ in range(5):
            msg = transport.receive("ordered", timeout=1.0)
            received.append(msg.payload)

        assert received == [0, 1, 2, 3, 4]
