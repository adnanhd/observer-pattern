"""Example 07: distributed workers over real TCP, N workers, round-robin.

Spins up N worker SUBPROCESSES, each running an ``RPCServer`` on a
distinct port. The driver process round-robins calls across the worker
pool. Demonstrates:

  - Cross-process TCP RPC (not in-memory shortcut).
  - JSON wire format (no pickle in the network path).
  - Trivial round-robin load balance across N workers.
  - Lifecycle: the driver starts subprocesses, calls them, shuts them down.

Each worker handler is the same: it receives a registry-pattern envelope,
reconstructs the model with ``registry.build``, runs a fake forward pass,
returns the prediction. Same handler as example 06; the wire-side is the
new piece.

Run::

    PYTHONPATH=/path/to/registry-pattern:. python examples/07_distributed_workers.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from itertools import cycle
from typing import Any

from registry import TypeRegistry, build, serialize

from callpyback import MessageQueue, RPCClient
from callpyback.transports.tcp import TCPClientTransport


# =============================================================================
# Domain
# =============================================================================


class ModelRegistry(TypeRegistry[Any], repo="examples.distributed.models"):
    pass


@ModelRegistry.register_artifact
class MLP:
    def __init__(self, in_features: int = 4, hidden: int = 8, out_features: int = 2) -> None:
        self.in_features = in_features
        self.hidden = hidden
        self.out_features = out_features

    def predict(self, x: list[float]) -> list[float]:
        return [sum(x) % (self.out_features or 1)] * self.out_features


# =============================================================================
# Worker entry -- spawned as a subprocess by the driver
# =============================================================================


WORKER_SOURCE = textwrap.dedent(
    """
    import sys, time
    from typing import Any
    from registry import TypeRegistry, build
    from callpyback import MessageQueue, RPCServer
    from callpyback.transports.tcp import TCPServerTransport

    class ModelRegistry(TypeRegistry[Any], repo="examples.distributed.models"):
        pass

    @ModelRegistry.register_artifact
    class MLP:
        def __init__(self, in_features=4, hidden=8, out_features=2):
            self.in_features = in_features
            self.hidden = hidden
            self.out_features = out_features
        def predict(self, x):
            return [sum(x) % (self.out_features or 1)] * self.out_features

    def handler(envelope, batch):
        model = build(envelope)
        return {
            "worker_pid": __import__("os").getpid(),
            "model_class": type(model).__name__,
            "prediction": model.predict(batch),
        }

    port = int(sys.argv[1])
    transport = TCPServerTransport(host="127.0.0.1", port=port)
    transport.start()
    queue = MessageQueue(transport=transport)
    server = RPCServer(queue, service_name="learner")
    server.add_method("train_step", handler)
    # Block in the foreground -- driver tears us down via SIGTERM.
    try:
        server.serve(blocking=True)
    except KeyboardInterrupt:
        pass
    finally:
        transport.close()
    """
)


def spawn_worker(port: int) -> subprocess.Popen:
    """Fork a subprocess running an RPCServer on `port`."""
    return subprocess.Popen(
        [sys.executable, "-c", WORKER_SOURCE, str(port)],
        env={**os.environ, "PYTHONPATH": ":".join(sys.path)},
    )


# =============================================================================
# Driver: spawn N workers, round-robin RPC calls, tear down
# =============================================================================


def main(n_workers: int = 3, base_port: int = 19090) -> None:
    ports = [base_port + i for i in range(n_workers)]
    workers = [spawn_worker(p) for p in ports]

    # Give the workers time to bind their sockets before we hit them.
    time.sleep(1.5)

    try:
        # One RPCClient per worker, round-robin between them.
        clients = []
        transports = []
        for p in ports:
            transport = TCPClientTransport(host="127.0.0.1", port=p)
            transport.connect()
            transports.append(transport)
            queue = MessageQueue(transport=transport)
            clients.append(RPCClient(queue, service_name="learner", timeout=5.0))

        # Build a serializable envelope locally via registry-pattern.
        local_model = MLP(in_features=4, hidden=32, out_features=2)
        envelope = serialize(local_model, serializator="python",
                             repo="examples.distributed.models")

        # Dispatch 9 calls round-robin across 3 workers.
        pid_counts: dict[int, int] = {}
        round_robin = cycle(clients)
        for i in range(9):
            client = next(round_robin)
            result = client.call("train_step", envelope, [1.0, 2.0, 3.0, float(i)])
            pid = result["worker_pid"]
            pid_counts[pid] = pid_counts.get(pid, 0) + 1
            print(f"call {i}: worker={pid} -> {result['prediction']}")

        print("\nload distribution by worker pid:", pid_counts)
        assert len(pid_counts) == n_workers, "round-robin should hit all workers"
    finally:
        for t in transports:
            t.close()
        for w in workers:
            w.terminate()
        for w in workers:
            w.wait(timeout=5.0)


if __name__ == "__main__":
    main()
