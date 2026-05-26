"""Tests for the Caller protocol and LocalProcedureCaller.call dispatch."""

import time

import pytest

from eventforge import (
    Caller,
    ExecutionMode,
    Executor,
    LocalProcedureCaller,
    MessageQueue,
    RPCClient,
    RPCServer,
    TimingMeter,
    task,
)


def test_call_sequential_returns_result() -> None:
    lpc = LocalProcedureCaller()

    def add(a: int, b: int) -> int:
        return a + b

    assert lpc.call(add, 2, 3) == 5


def test_call_thread_mode_returns_result() -> None:
    lpc = LocalProcedureCaller(mode=ExecutionMode.THREAD)

    def mul(a: int, b: int) -> int:
        return a * b

    assert lpc.call(mul, 4, 5) == 20


def test_executor_is_alias_and_instance_is_caller() -> None:
    assert Executor is LocalProcedureCaller
    lpc = LocalProcedureCaller()
    assert isinstance(lpc, Caller)


def test_call_non_callable_raises_type_error() -> None:
    lpc = LocalProcedureCaller()
    with pytest.raises(TypeError):
        lpc.call("not-callable")


def test_task_fn_registered_on_server_runs_with_observability() -> None:
    # The recommended remote pattern: a @task-decorated function registered
    # on an RPCServer runs ON the server (with its observers) when a client
    # calls it by name. No client-side stub, no duplication.
    queue = MessageQueue()
    timing = TimingMeter()

    @task(on_execute=[timing])
    def predict(x: int) -> int:
        return x * 2

    server = RPCServer(queue, service_name="ml")
    server.add_method("predict", predict)
    server.serve(blocking=False)
    time.sleep(0.1)

    client = RPCClient(queue, service_name="ml", timeout=5.0)
    try:
        assert client.call("predict", 5) == 10
        # Observers fired on the server side, around the real execution.
        assert timing.stats["count"] >= 1
    finally:
        server.stop()
