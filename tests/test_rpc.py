"""Tests for eventforge.rpc module."""

import time

import pytest

from eventforge import (
    Executor,
    MessageQueue,
    RPCClient,
    RPCServer,
    TimingMeter,
    task,
)


class TestRPC:
    def test_basic_rpc_call(self):
        queue = MessageQueue()
        executor = Executor()

        server = RPCServer(queue, executor, service_name="test")

        @server.register()
        def add(a: int, b: int) -> int:
            return a + b

        # Start server in background
        server.serve(blocking=False)
        time.sleep(0.1)  # Give server time to start

        client = RPCClient(queue, service_name="test", timeout=5.0)
        result = client.call("add", 10, 20)

        assert result == 30

        server.stop()

    def test_multiple_methods(self):
        queue = MessageQueue()
        executor = Executor()

        server = RPCServer(queue, executor, service_name="math")

        @server.register()
        def add(a, b):
            return a + b

        @server.register()
        def multiply(a, b):
            return a * b

        @server.register()
        def subtract(a, b):
            return a - b

        server.serve(blocking=False)
        time.sleep(0.1)

        client = RPCClient(queue, service_name="math")

        assert client.call("add", 5, 3) == 8
        assert client.call("multiply", 5, 3) == 15
        assert client.call("subtract", 5, 3) == 2

        server.stop()

    def test_custom_method_name(self):
        queue = MessageQueue()
        executor = Executor()

        server = RPCServer(queue, executor, service_name="svc")

        @server.register(name="double_value")
        def my_internal_function(x):
            return x * 2

        server.serve(blocking=False)
        time.sleep(0.1)

        client = RPCClient(queue, service_name="svc")
        result = client.call("double_value", 21)

        assert result == 42

        server.stop()

    def test_dynamic_method_access(self):
        queue = MessageQueue()
        executor = Executor()

        server = RPCServer(queue, executor, service_name="api")

        @server.register()
        def greet(name):
            return f"Hello, {name}!"

        server.serve(blocking=False)
        time.sleep(0.1)

        client = RPCClient(queue, service_name="api")

        # Dynamic access: client.method_name(...)
        result = client.greet("World")

        assert result == "Hello, World!"

        server.stop()

    def test_kwargs_support(self):
        queue = MessageQueue()
        executor = Executor()

        server = RPCServer(queue, executor, service_name="config")

        @server.register()
        def configure(host="localhost", port=8080, debug=False):
            return {"host": host, "port": port, "debug": debug}

        server.serve(blocking=False)
        time.sleep(0.1)

        client = RPCClient(queue, service_name="config")
        result = client.call("configure", port=9000, debug=True)

        assert result["host"] == "localhost"
        assert result["port"] == 9000
        assert result["debug"] is True

        server.stop()

    def test_method_error(self):
        queue = MessageQueue()
        executor = Executor()

        server = RPCServer(queue, executor, service_name="errors")

        @server.register()
        def failing_method():
            raise ValueError("Something went wrong")

        server.serve(blocking=False)
        time.sleep(0.1)

        client = RPCClient(queue, service_name="errors")

        with pytest.raises(Exception) as exc_info:
            client.call("failing_method")

        assert "Something went wrong" in str(exc_info.value)

        server.stop()

    def test_method_not_found(self):
        queue = MessageQueue()
        executor = Executor()

        server = RPCServer(queue, executor, service_name="limited")
        server.serve(blocking=False)
        time.sleep(0.1)

        client = RPCClient(queue, service_name="limited", timeout=1.0)

        with pytest.raises(Exception) as exc_info:
            client.call("nonexistent_method")

        assert "Method not found" in str(exc_info.value)

        server.stop()

    def test_client_timeout(self):
        queue = MessageQueue()

        # No server running, so calls will timeout
        client = RPCClient(queue, service_name="noserver", timeout=0.2)

        with pytest.raises(TimeoutError):
            client.call("any_method")

    def test_add_method_directly(self):
        queue = MessageQueue()
        executor = Executor()

        server = RPCServer(queue, executor, service_name="direct")

        def square(x):
            return x * x

        server.add_method("square", square)

        server.serve(blocking=False)
        time.sleep(0.1)

        client = RPCClient(queue, service_name="direct")
        result = client.call("square", 5)

        assert result == 25

        server.stop()

    def test_server_context_manager(self):
        queue = MessageQueue()
        executor = Executor()

        with RPCServer(queue, executor, service_name="ctx") as server:

            @server.register()
            def echo(msg):
                return msg

            server.serve(blocking=False)
            time.sleep(0.1)

            client = RPCClient(queue, service_name="ctx")
            result = client.call("echo", "hello")

            assert result == "hello"

    def test_task_handler_runs_with_server_side_observability(self):
        # A @task-decorated function registered on an RPCServer runs ON the
        # server (with its observers) when a client calls it by name.
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
