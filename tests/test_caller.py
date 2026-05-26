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


def test_rpc_client_is_caller() -> None:
    client = RPCClient(MessageQueue(), service_name="x")
    assert isinstance(client, Caller)


def test_task_dispatches_by_name_to_remote() -> None:
    queue = MessageQueue()
    server = RPCServer(queue, service_name="ml")

    @server.register("predict")
    def server_predict(x: int) -> int:
        # The server computes a distinctive value so we can prove the
        # remote method ran rather than the local stub body.
        return x * 100

    server.serve(blocking=False)
    time.sleep(0.1)

    client = RPCClient(queue, service_name="ml", timeout=5.0)

    @task(caller=client)
    def predict(x: int) -> int:
        # Stub body -- never executed; the remote "predict" runs instead.
        return -1

    try:
        result = predict(5)
        assert result == 500
    finally:
        server.stop()
