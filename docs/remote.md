# Remote Queue

A push-only switchboard that routes messages to peer nodes over owned TCP
links.

## Overview

`RemoteQueue` is a node-addressing layer on top of `MessageQueue`. It owns
one outbound TCP client link per peer and routes `send` / `broadcast` to
them; it receives via an optional `local` MessageQueue (typically backed by
a `TCPServerTransport`) that peers publish into.

The model is **push-only**, matching an in-process task runner's remote
story -- a coordinator sends work out, workers send results back:

- `send(node_id, topic, payload)` -- push to ONE peer
- `broadcast(topic, payload)` -- push to ALL peers
- `subscribe(topic, handler)` / `on(topic)` -- receive (peers publish to us)

There is deliberately no "subscribe into a peer's private topic" (pull):
that direction is request-reply -- use [RPC](rpc.md) -- or just have the
peer publish to you.

A node needs a `local` queue **only if it receives**. A pure sender does
not.

## Basic Usage

```python
from eventforge import MessageQueue, RemoteQueue
from eventforge.transports.tcp import TCPServerTransport

# --- Worker: RECEIVES, so it listens on a port and subscribes locally. ---
# (TCPServerTransport must be .start()ed before use.)
worker_srv = TCPServerTransport(host="0.0.0.0", port=9001)
worker_srv.start()
worker = RemoteQueue("worker-1", local=MessageQueue(transport=worker_srv))

@worker.on("work")
def run(msg):
    print(f"worker got: {msg.payload}")

# --- Coordinator: only SENDS, so it needs no local queue at all. ---
coord = RemoteQueue("coordinator")
coord.connect("worker-1", host="127.0.0.1", port=9001)  # own a TCP link by address

coord.send("worker-1", "work", {"task": 42})  # push to one peer
# -> worker got: {'task': 42}
```

## Sending to Peers

```python
# Push to a single named peer (-> message id)
msg_id = coord.send("worker-1", "work", {"task": 42})

# Push to every connected peer (-> {node_id: message_id})
ids = coord.broadcast("shutdown", {})
print(ids)  # {"worker-1": "...", "worker-2": "..."}
```

`send` raises `KeyError` if you are not connected to that node id.

## Receiving (the `local` queue)

`subscribe` / `on` attach handlers to this node's `local` MessageQueue,
which is how peers reach you. Calling them on a node that was created
*without* a `local` raises `RuntimeError`.

```python
from eventforge import MessageQueue, RemoteQueue
from eventforge.transports.tcp import TCPServerTransport

srv = TCPServerTransport(host="0.0.0.0", port=9002)
srv.start()  # start the server transport before it can receive
node = RemoteQueue("node-2", local=MessageQueue(transport=srv))

@node.on("results")
def on_result(msg):
    print(msg.payload)

# or, non-decorator:
def handler(msg):
    print(msg.payload)

sub_id = node.subscribe("results", handler)
```

## Connection Management

```python
coord = RemoteQueue("coordinator")

# Open + own an outbound TCP link to a peer (replaces any existing link).
coord.connect("worker-1", host="127.0.0.1", port=9001)

# Currently connected peer node ids.
print(coord.peers)        # ['worker-1']
print(coord.node_id)      # 'coordinator'

# Close one link (-> True if it existed).
coord.disconnect("worker-1")

# Context manager: closes every peer link and the local queue on exit.
with RemoteQueue("coordinator") as coord:
    coord.connect("worker-1", host="127.0.0.1", port=9001)
    coord.send("worker-1", "work", {"task": 1})
# all links + local queue closed here
```

## API Reference

### RemoteQueue

```python
class RemoteQueue:
    def __init__(self, node_id: str, *, local: MessageQueue | None = None):
        """Switchboard for one node.

        local: MessageQueue this node receives on, e.g.
            MessageQueue(TCPServerTransport(host="0.0.0.0", port=9001)).
            Required for subscribe() / on(); send() / broadcast() work
            without it.
        """

    @property
    def node_id(self) -> str: ...

    @property
    def local(self) -> MessageQueue | None: ...

    @property
    def peers(self) -> list[str]:
        """Currently connected peer node ids."""

    def connect(self, node_id: str, host: str, port: int) -> None:
        """Open and own an outbound TCP link to a peer (replaces existing)."""

    def disconnect(self, node_id: str) -> bool:
        """Close the link to a peer. Returns True if it existed."""

    def send(self, node_id: str, topic: str, payload: Any, **headers) -> str:
        """Push a message to one peer. Returns the message id."""

    def broadcast(self, topic: str, payload: Any, **headers) -> dict[str, str]:
        """Push to every connected peer. Returns {node_id: message_id}."""

    def subscribe(self, topic: str, handler: Callable) -> str:
        """Subscribe a handler on the local queue (how peers reach us)."""

    def on(self, topic: str) -> Callable:
        """Decorator form of subscribe; returns the handler unchanged."""

    def close(self) -> None:
        """Close every peer link and the local queue."""
```

## Examples

### Coordinator / Worker Pool

```python
from eventforge import MessageQueue, RemoteQueue
from eventforge.transports.tcp import TCPServerTransport

# --- Workers: each listens on its own port and subscribes locally. ---
def make_worker(node_id: str, port: int) -> RemoteQueue:
    srv = TCPServerTransport(host="0.0.0.0", port=port)
    srv.start()
    worker = RemoteQueue(node_id, local=MessageQueue(transport=srv))

    @worker.on("work")
    def run(msg, _node=node_id):
        print(f"{_node} got: {msg.payload}")

    return worker

workers = {
    "worker-1": make_worker("worker-1", 9101),
    "worker-2": make_worker("worker-2", 9102),
}

# --- Coordinator: pure sender, no local queue. ---
coord = RemoteQueue("coordinator")
coord.connect("worker-1", host="127.0.0.1", port=9101)
coord.connect("worker-2", host="127.0.0.1", port=9102)

# Dispatch to one peer or fan out to all of them.
coord.send("worker-1", "work", {"task": 1})
coord.broadcast("work", {"task": "ping"})
```

### Bidirectional (workers push results back)

To get results back, give the coordinator a `local` queue too and have each
worker `send` to it. The coordinator subscribes locally for the results
topic; the worker connects an outbound link back to the coordinator.

```python
from eventforge import MessageQueue, RemoteQueue
from eventforge.transports.tcp import TCPServerTransport

# Coordinator now also RECEIVES, so it listens + subscribes.
coord_srv = TCPServerTransport(host="0.0.0.0", port=9000)
coord_srv.start()
coord = RemoteQueue("coordinator", local=MessageQueue(transport=coord_srv))

@coord.on("results")
def on_result(msg):
    print(f"coordinator got result: {msg.payload}")

# A worker opens its own outbound link back to the coordinator and pushes.
worker = RemoteQueue("worker-1")  # only sends here
worker.connect("coordinator", host="127.0.0.1", port=9000)
worker.send("coordinator", "results", {"task": 1, "value": 42})
```

For *pulling* a value from a peer (request-reply), use [RPC](rpc.md) rather
than `RemoteQueue`: `RemoteQueue` is push-only by design.
