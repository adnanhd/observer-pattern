"""Multi-node switchboard over MessageQueue + TCP transports.

``RemoteQueue`` is a node-addressing layer on top of :class:`MessageQueue`.
It owns one outbound TCP client link per peer and routes ``send`` /
``broadcast`` to them; it receives via an optional ``local`` MessageQueue
(typically backed by a ``TCPServerTransport``) that peers publish into.

The model is **push-only**, matching an in-process task runner's remote
story -- a coordinator sends work out, workers send results back:

  - ``send(node, topic, payload)``      push to ONE peer
  - ``broadcast(topic, payload)``       push to ALL peers
  - ``subscribe(topic, handler)``       receive (peers publish to us)

There is deliberately no "subscribe into a peer's private topic" (pull):
that direction is request-reply -- use :class:`eventforge.RPCClient` -- or
just have the peer publish to you.
"""

from __future__ import annotations
from typing import Dict, List, Optional

import threading
from typing import Any

from eventforge.queue import Handler, MessageQueue
from eventforge.transports.tcp import TCPClientTransport


class RemoteQueue:
    """Switchboard routing messages to N peer nodes over owned TCP links.

    Args:
        node_id: identity of this node.
        local: optional MessageQueue this node receives on, e.g.
            ``MessageQueue(TCPServerTransport(host="0.0.0.0", port=9001))``.
            Required for :meth:`subscribe` / :meth:`on`; ``send`` /
            ``broadcast`` work without it.

    Example::

        local = MessageQueue(TCPServerTransport(host="0.0.0.0", port=9001))
        rq = RemoteQueue("node-1", local=local)
        rq.connect("node-2", host="10.0.0.2", port=9002)

        @rq.on("results")                    # receive: peers publish to us
        def on_result(msg):
            print(msg.payload)

        rq.send("node-2", "work", {"x": 1})  # push to one peer
        rq.broadcast("shutdown", {})         # push to all peers
    """

    def __init__(self, node_id: str, *, local: Optional[MessageQueue] = None) -> None:
        self._node_id = node_id
        self._local = local
        self._peers: Dict[str, MessageQueue] = {}
        self._transports: Dict[str, TCPClientTransport] = {}
        self._lock = threading.RLock()

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def local(self) -> Optional[MessageQueue]:
        return self._local

    @property
    def peers(self) -> List[str]:
        """Currently connected peer node ids."""
        with self._lock:
            return list(self._peers)

    # -- peer links ---------------------------------------------------------

    def connect(self, node_id: str, host: str, port: int) -> None:
        """Open and own an outbound TCP link to a peer (replaces any existing)."""
        transport = TCPClientTransport(host=host, port=port)
        transport.connect()
        with self._lock:
            old = self._transports.pop(node_id, None)
            self._transports[node_id] = transport
            self._peers[node_id] = MessageQueue(transport=transport)
        if old is not None:
            old.close()

    def disconnect(self, node_id: str) -> bool:
        """Close the link to a peer. Returns True if it existed."""
        with self._lock:
            self._peers.pop(node_id, None)
            transport = self._transports.pop(node_id, None)
        if transport is None:
            return False
        transport.close()
        return True

    # -- push to peers ------------------------------------------------------

    def send(self, node_id: str, topic: str, payload: Any, **headers: Any) -> str:
        """Push a message to one peer. Returns the message id."""
        with self._lock:
            peer = self._peers.get(node_id)
        if peer is None:
            raise KeyError(f"not connected to node {node_id!r}")
        return peer.publish(topic, payload, **headers)

    def broadcast(self, topic: str, payload: Any, **headers: Any) -> Dict[str, str]:
        """Push a message to every connected peer. Returns ``{node_id: msg_id}``."""
        with self._lock:
            peers = dict(self._peers)
        return {
            node_id: peer.publish(topic, payload, **headers)
            for node_id, peer in peers.items()
        }

    # -- local receive ------------------------------------------------------

    def subscribe(self, topic: str, handler: Handler) -> str:
        """Subscribe a handler on the local queue (how peers reach us)."""
        return self._require_local().subscribe(topic, handler)

    def on(self, topic: str) -> Any:
        """Decorator form of :meth:`subscribe`; returns the handler unchanged."""

        def deco(handler: Handler) -> Handler:
            self.subscribe(topic, handler)
            return handler

        return deco

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        """Close every peer link and the local queue."""
        with self._lock:
            transports = list(self._transports.values())
            self._transports.clear()
            self._peers.clear()
        for transport in transports:
            transport.close()
        if self._local is not None:
            self._local.close()

    def _require_local(self) -> MessageQueue:
        if self._local is None:
            raise RuntimeError(
                "this RemoteQueue was created without a local queue; "
                "pass RemoteQueue(node_id, local=MessageQueue(...)) to receive."
            )
        return self._local

    def __enter__(self) -> RemoteQueue:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
