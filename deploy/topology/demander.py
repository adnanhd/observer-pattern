"""Demander node: round-robins RPC calls across the eventforge server pool.

This is the *client* side of the topology. It reads the server list from
``EVENTFORGE_SERVERS`` (comma-separated ``host:port``), opens one
``RPCClient`` per server, wraps them in a ``RoundRobinRPCClient``, and
fires a batch of calls. Because each handler reports its serving
hostname/pid, the final tally shows the load spread across servers.

Note the topology's defining trait: load balancing is **client-side**.
The demander must know every server address up front -- there is no
broker and no service discovery. That is the honest shape of an
eventforge-network: an RPC compute-worker pool on a trusted network.

Run (inside the compose network)::

    EVENTFORGE_SERVERS=server1:9090,server2:9090,server3:9090 python demander.py
"""

from __future__ import annotations

import os
import time

from eventforge import MessageQueue, RPCClient, RoundRobinRPCClient
from eventforge.transports.tcp import TCPClientTransport

SERVERS = os.environ.get(
    "EVENTFORGE_SERVERS", "server1:9090,server2:9090,server3:9090"
).split(",")
SERVICE = os.environ.get("EVENTFORGE_SERVICE", "math")
N_CALLS = int(os.environ.get("EVENTFORGE_CALLS", "12"))


def _connect_with_retry(host: str, port: int, attempts: int = 30) -> TCPClientTransport:
    """Servers may still be binding when the demander starts; retry."""
    last_exc: Exception | None = None
    for i in range(attempts):
        transport = TCPClientTransport(host=host, port=port)
        try:
            transport.connect()
            return transport
        except (ConnectionError, OSError) as exc:
            last_exc = exc
            time.sleep(0.5)
    raise SystemExit(f"demander: could not connect to {host}:{port}: {last_exc}")


def main() -> None:
    clients = []
    for addr in SERVERS:
        host, _, port = addr.strip().partition(":")
        transport = _connect_with_retry(host, int(port))
        queue = MessageQueue(transport=transport)
        clients.append(RPCClient(queue, service_name=SERVICE, timeout=5.0))
        print(f"demander: connected to {addr}")

    pool = RoundRobinRPCClient(clients)

    print(f"\ndemander: firing {N_CALLS} 'compute' calls round-robin...\n")
    by_server: dict[str, int] = {}
    for i in range(N_CALLS):
        res = pool.call("compute", float(i))
        # host alone collides when servers share a machine (loopback demo);
        # host#pid is unique both on one host and across containers.
        server = f"{res['host']}#{res['pid']}"
        by_server[server] = by_server.get(server, 0) + 1
        print(f"  call {i:2d}: served by {server} -> {res['result']}")

    print("\ndemander: load distribution by server:")
    for server, count in sorted(by_server.items()):
        print(f"  {server}: {count} calls")
    print(f"\ndemander: spread across {len(by_server)} servers. done.")


if __name__ == "__main__":
    main()
