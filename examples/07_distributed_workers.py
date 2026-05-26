"""Example 07: distributed workers over real TCP, N workers, round-robin.

Spins up N worker SUBPROCESSES, each an ``RPCServer`` on a distinct port,
then round-robins calls across the pool. Demonstrates:

  - Cross-process TCP RPC (not the in-memory shortcut).
  - JSON wire format (no pickle in the network path).
  - Round-robin load balance via ``RoundRobinRPCClient``.
  - Lifecycle: the driver starts subprocesses, calls them, shuts them down.

The workers are spawned with the ``eventforge.worker`` entrypoint pointed
at ``distributed_handlers`` -- the same module/contract that
``deploy/topology/handlers.py`` bind-mounts into a container, so this
example is the local rehearsal of the containerized topology in
``deploy/``. The bind/serve internals the entrypoint runs live in
``eventforge/worker.py``; the domain + handler live in
``examples/distributed_handlers.py``.

Run::

    PYTHONPATH=/path/to/registry-pattern:examples \
        python examples/07_distributed_workers.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

# Domain + handler + entrypoint contract (HANDLERS / SERVICE_NAME) live here.
# Importing it also registers MLP in the ModelRegistry for the local serialize.
from distributed_handlers import MLP, SERVICE_NAME  # noqa: E402
from registry import serialize

from eventforge import MessageQueue, RoundRobinRPCClient, RPCClient
from eventforge.transports.tcp import TCPClientTransport

# =============================================================================
# Worker entry -- spawned via the eventforge.worker entrypoint (no inlined src)
# =============================================================================


def spawn_worker(port: int) -> subprocess.Popen:
    """Spawn an RPC server worker on `port` via `python -m eventforge.worker`.

    The worker imports ``distributed_handlers``, finds its ``HANDLERS``
    table, and serves each entry -- no stringified worker source, no
    duplicated domain code. PYTHONPATH is forwarded so the subprocess can
    import both registry-pattern and the handler module.
    """
    return subprocess.Popen(
        [
            sys.executable, "-m", "eventforge.worker",
            "--import", "distributed_handlers",
            "--service", SERVICE_NAME,
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", "WARNING",
        ],
        env={**os.environ, "PYTHONPATH": ":".join(sys.path)},
    )


# =============================================================================
# Driver: spawn N workers, round-robin RPC calls, tear down
# =============================================================================


def main(n_workers: int = 3, base_port: int = 19090) -> None:
    ports = [base_port + i for i in range(n_workers)]
    workers = [spawn_worker(p) for p in ports]

    # Give the workers time to import + bind their sockets before we hit them.
    time.sleep(2.0)

    transports = []
    try:
        # One RPCClient per worker; RoundRobinRPCClient does the load balance.
        clients = []
        for p in ports:
            transport = TCPClientTransport(host="127.0.0.1", port=p)
            transport.connect()
            transports.append(transport)
            queue = MessageQueue(transport=transport)
            clients.append(RPCClient(queue, service_name=SERVICE_NAME, timeout=5.0))
        pool = RoundRobinRPCClient(clients)

        # Build a serializable envelope locally via registry-pattern.
        local_model = MLP(in_features=4, hidden=32, out_features=2)
        envelope = serialize(
            local_model, serializator="python", repo="examples.distributed.models"
        )

        # Dispatch 9 calls round-robin across the worker pool.
        pid_counts: dict[int, int] = {}
        for i in range(9):
            result = pool.call("train_step", envelope, [1.0, 2.0, 3.0, float(i)])
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
