"""Tests for RoundRobinRPCClient and with_retry."""

from __future__ import annotations

import threading
import time
from typing import Any, List

import pytest

from callpyback import (
    MessageQueue,
    RoundRobinRPCClient,
    RPCClient,
    RPCServer,
    with_retry,
)

# =============================================================================
# RoundRobinRPCClient
# =============================================================================


def test_round_robin_dispatches_across_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each call() hits a different client in rotation."""

    class _StubClient:
        def __init__(self, name: str) -> None:
            self.name = name
            self.calls: List[Any] = []

        def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
            self.calls.append((method, args))
            return self.name

    clients = [_StubClient("A"), _StubClient("B"), _StubClient("C")]
    lb = RoundRobinRPCClient(clients)  # type: ignore[arg-type]

    visits = [lb.call("echo", i) for i in range(6)]
    assert visits == ["A", "B", "C", "A", "B", "C"]
    assert [len(c.calls) for c in clients] == [2, 2, 2]


def test_round_robin_rejects_empty_pool() -> None:
    with pytest.raises(ValueError, match="at least one"):
        RoundRobinRPCClient([])


def test_round_robin_dynamic_attr_dispatches() -> None:
    """``lb.foo(...)`` should route through ``call("foo", ...)``."""

    class _StubClient:
        def __init__(self) -> None:
            self.calls: List[Any] = []

        def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
            self.calls.append((method, args, kwargs))
            return f"{method}={args}"

    lb = RoundRobinRPCClient([_StubClient()])  # type: ignore[arg-type]
    assert lb.foo(1, 2) == "foo=(1, 2)"  # type: ignore[attr-defined]


# =============================================================================
# with_retry
# =============================================================================


def test_with_retry_succeeds_after_transient_failures() -> None:
    """Client that fails N-1 times, succeeds on attempt N."""

    class _FlakyClient:
        def __init__(self, fail_n_times: int) -> None:
            self.attempts = 0
            self.fail_n_times = fail_n_times

        def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
            self.attempts += 1
            if self.attempts <= self.fail_n_times:
                raise TimeoutError(f"flake {self.attempts}")
            return "ok"

    flaky = _FlakyClient(fail_n_times=2)
    resilient = with_retry(
        flaky,  # type: ignore[arg-type]
        max_retries=3,
        backoff_initial=0.001,
    )
    assert resilient.call("ping") == "ok"
    assert flaky.attempts == 3


def test_with_retry_exhausts_attempts_and_raises() -> None:
    """If failures exceed max_retries, last exception propagates."""

    class _AlwaysFails:
        def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
            raise TimeoutError("nope")

    resilient = with_retry(
        _AlwaysFails(),  # type: ignore[arg-type]
        max_retries=2,
        backoff_initial=0.001,
    )
    with pytest.raises(TimeoutError, match="nope"):
        resilient.call("ping")


def test_with_retry_does_not_retry_non_matching_exception() -> None:
    """Application errors (not in retry_on) propagate immediately."""

    class _AppErrorClient:
        def __init__(self) -> None:
            self.attempts = 0

        def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
            self.attempts += 1
            raise ValueError("application error")

    client = _AppErrorClient()
    resilient = with_retry(
        client,  # type: ignore[arg-type]
        max_retries=5,
        backoff_initial=0.001,
    )
    with pytest.raises(ValueError):
        resilient.call("ping")
    assert client.attempts == 1


# =============================================================================
# Integration: RoundRobin + retry over real (in-memory) RPC server
# =============================================================================


def test_round_robin_integration_with_real_rpc_server() -> None:
    """Plug round-robin client onto two RPCServers sharing a queue.

    The two servers share the same in-memory MessageQueue (so dispatch is
    actually first-come-first-serve from the queue) -- we just verify the
    end-to-end call works without exceptions.
    """
    queue = MessageQueue()
    server = RPCServer(queue, service_name="rr_test")
    server.add_method("echo", lambda x: x * 2)
    server.serve(blocking=False)

    try:
        c1 = RPCClient(queue, service_name="rr_test", timeout=5.0)
        c2 = RPCClient(queue, service_name="rr_test", timeout=5.0)
        lb = RoundRobinRPCClient([c1, c2])

        results = [lb.call("echo", i) for i in range(4)]
        assert results == [0, 2, 4, 6]
    finally:
        server.stop()
