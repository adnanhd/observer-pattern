"""Tests for the rebuilt RemoteQueue switchboard (TCP round-trips)."""

import socket
import time

import pytest

from eventforge import MessageQueue, RemoteQueue
from eventforge.transports.tcp import TCPServerTransport


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port: int = s.getsockname()[1]
    s.close()
    return port


def _node(node_id: str, port: int) -> RemoteQueue:
    server = TCPServerTransport(host="127.0.0.1", port=port)
    server.start()
    return RemoteQueue(node_id, local=MessageQueue(transport=server))


def _wait(predicate, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_send_reaches_one_peer() -> None:
    p1, p2 = _free_port(), _free_port()
    n1, n2 = _node("node-1", p1), _node("node-2", p2)
    received: list = []

    @n1.on("events.order")
    def _handle(msg) -> None:
        received.append(msg.payload)

    n2.connect("node-1", host="127.0.0.1", port=p1)
    try:
        n2.send("node-1", "events.order", {"id": 123})
        assert _wait(lambda: bool(received)), "message never arrived"
        assert received[0] == {"id": 123}
    finally:
        n1.close()
        n2.close()


def test_broadcast_hits_all_peers() -> None:
    p1, p2, ph = _free_port(), _free_port(), _free_port()
    n1, n2, hub = _node("node-1", p1), _node("node-2", p2), _node("hub", ph)
    got1: list = []
    got2: list = []
    n1.on("sys")(lambda m: got1.append(m.payload))
    n2.on("sys")(lambda m: got2.append(m.payload))

    hub.connect("node-1", host="127.0.0.1", port=p1)
    hub.connect("node-2", host="127.0.0.1", port=p2)
    try:
        ids = hub.broadcast("sys", {"action": "ping"})
        assert set(ids) == {"node-1", "node-2"}
        assert _wait(lambda: bool(got1) and bool(got2)), "broadcast missed a peer"
    finally:
        for node in (n1, n2, hub):
            node.close()


def test_send_to_unknown_peer_raises() -> None:
    rq = RemoteQueue("solo")
    with pytest.raises(KeyError):
        rq.send("nope", "t", {})


def test_subscribe_without_local_raises() -> None:
    rq = RemoteQueue("solo")
    with pytest.raises(RuntimeError):
        rq.subscribe("t", lambda m: None)


def test_peers_and_disconnect() -> None:
    p1 = _free_port()
    server = _node("node-1", p1)
    client = RemoteQueue("client")
    client.connect("node-1", host="127.0.0.1", port=p1)
    try:
        assert client.peers == ["node-1"]
        assert client.disconnect("node-1") is True
        assert client.peers == []
        assert client.disconnect("missing") is False
    finally:
        server.close()
        client.close()
