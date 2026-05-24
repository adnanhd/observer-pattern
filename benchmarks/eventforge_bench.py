#!/usr/bin/env python
"""Quick benchmarks for eventforge hot paths.

Two angles:

1. ``@task`` lifecycle overhead in local-process mode -- bare function
   call vs. ``@task``-decorated, no observers vs. one observer attached.
2. RPC roundtrip latency over an in-memory MessageQueue and over TCP.

Numbers are wall-clock medians on a single machine. Not a substitute
for proper profiling -- just a smell-test for regression catches.

Run::

    PYTHONPATH=. python benchmarks/eventforge_bench.py
"""

from __future__ import annotations

import gc
import statistics
import threading
import time
from typing import Any, List

from eventforge import (
    ExecutionMode,
    Executor,
    MessageQueue,
    Observer,
    RPCClient,
    RPCServer,
    TimingMeter,
    task,
)
from eventforge.transports.tcp import TCPClientTransport, TCPServerTransport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def timeit_ms(fn: Any, *, runs: int = 200, warmup: int = 50) -> dict[str, float]:
    """Median + p95 latency of `fn()` in milliseconds."""
    for _ in range(warmup):
        fn()
    samples: List[float] = []
    for _ in range(runs):
        gc.collect()
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    return {
        "median_ms": statistics.median(samples),
        "p95_ms": samples[int(0.95 * len(samples)) - 1],
        "mean_ms": statistics.mean(samples),
    }


# ---------------------------------------------------------------------------
# Benchmark 1: @task overhead
# ---------------------------------------------------------------------------


def bench_task_overhead() -> None:
    print("=" * 60)
    print("Benchmark 1: @task lifecycle overhead")
    print("=" * 60)

    def bare(x: int) -> int:
        return x * 2

    decorated = task()(bare)

    timing = TimingMeter()
    decorated_observed = task(on_execute=[timing])(bare)

    cases = {
        "bare function call         ": lambda: bare(7),
        "@task() no observer        ": lambda: decorated(7),
        "@task() with TimingMeter": lambda: decorated_observed(7),
    }
    for label, fn in cases.items():
        stats = timeit_ms(fn)
        print(
            f"{label}  median={stats['median_ms']:7.4f} ms  p95={stats['p95_ms']:7.4f} ms"
        )


# ---------------------------------------------------------------------------
# Benchmark 2: RPC roundtrip latency (in-memory vs. TCP)
# ---------------------------------------------------------------------------


def bench_rpc_roundtrip() -> None:
    print()
    print("=" * 60)
    print("Benchmark 2: RPC roundtrip latency")
    print("=" * 60)

    # 2a: in-memory queue
    inmem_queue = MessageQueue()
    inmem_server = RPCServer(inmem_queue, service_name="bench")
    inmem_server.add_method("echo", lambda x: x)
    inmem_server.serve(blocking=False)

    try:
        inmem_client = RPCClient(inmem_queue, service_name="bench", timeout=5.0)
        stats = timeit_ms(lambda: inmem_client.call("echo", 42), runs=200, warmup=20)
        print(
            f"in-memory queue            median={stats['median_ms']:7.4f} ms  p95={stats['p95_ms']:7.4f} ms"
        )
    finally:
        inmem_server.stop()

    # 2b: TCP roundtrip
    server_transport = TCPServerTransport(host="127.0.0.1", port=29090)
    server_transport.start()
    server_queue = MessageQueue(transport=server_transport)
    tcp_server = RPCServer(server_queue, service_name="bench")
    tcp_server.add_method("echo", lambda x: x)
    tcp_server.serve(blocking=False)

    # Let the listener bind.
    time.sleep(0.5)
    client_transport = TCPClientTransport(host="127.0.0.1", port=29090)
    client_transport.connect()
    client_queue = MessageQueue(transport=client_transport)
    tcp_client = RPCClient(client_queue, service_name="bench", timeout=5.0)

    try:
        stats = timeit_ms(lambda: tcp_client.call("echo", 42), runs=200, warmup=20)
        print(
            f"localhost TCP             median={stats['median_ms']:7.4f} ms  p95={stats['p95_ms']:7.4f} ms"
        )
    finally:
        tcp_server.stop()
        client_transport.close()
        server_transport.close()


def main() -> None:
    bench_task_overhead()
    bench_rpc_roundtrip()


if __name__ == "__main__":
    main()
