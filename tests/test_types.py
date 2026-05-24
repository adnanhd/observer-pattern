"""Tests for eventforge.types module."""

from datetime import datetime

import pytest

from eventforge.types import (
    Message,
    RPCRequest,
    RPCResponse,
    TaskRequest,
    TaskResult,
    TaskStatus,
)


class TestTaskStatus:
    def test_status_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.CANCELLED == "cancelled"


class TestMessage:
    def test_create_message(self):
        msg = Message(topic="test.topic", payload={"key": "value"})
        assert msg.topic == "test.topic"
        assert msg.payload == {"key": "value"}
        assert msg.id is not None
        assert isinstance(msg.timestamp, datetime)

    def test_message_with_headers(self):
        msg = Message(
            topic="test",
            payload="data",
            headers={"content-type": "application/json"},
        )
        assert msg.headers == {"content-type": "application/json"}

    def test_message_with_reply_to(self):
        msg = Message(
            topic="request",
            payload="query",
            reply_to="response.channel",
            correlation_id="abc123",
        )
        assert msg.reply_to == "response.channel"
        assert msg.correlation_id == "abc123"


class TestTaskRequest:
    def test_create_task_request(self):
        req = TaskRequest(func_name="my_function")
        assert req.func_name == "my_function"
        assert req.args == ()
        assert req.kwargs == {}

    def test_task_request_with_args(self):
        req = TaskRequest(
            func_name="compute",
            args=(1, 2, 3),
            kwargs={"multiplier": 10},
        )
        assert req.args == (1, 2, 3)
        assert req.kwargs == {"multiplier": 10}


class TestTaskResult:
    def test_success_result(self):
        result = TaskResult(
            task_id="task-1",
            status=TaskStatus.COMPLETED,
            value=42,
            execution_time=0.5,
        )
        assert result.task_id == "task-1"
        assert result.status == TaskStatus.COMPLETED
        assert result.value == 42
        assert result.is_success is True
        assert result.error is None

    def test_failure_result(self):
        result = TaskResult(
            task_id="task-2",
            status=TaskStatus.FAILED,
            error="Something went wrong",
            error_type="ValueError",
        )
        assert result.status == TaskStatus.FAILED
        assert result.is_success is False
        assert result.error == "Something went wrong"
        assert result.error_type == "ValueError"


class TestRPCRequest:
    def test_create_rpc_request(self):
        req = RPCRequest(method="add", args=(1, 2))
        assert req.method == "add"
        assert req.args == (1, 2)
        assert req.id is not None

    def test_rpc_request_with_kwargs(self):
        req = RPCRequest(method="compute", kwargs={"x": 10, "y": 20})
        assert req.kwargs == {"x": 10, "y": 20}


class TestRPCResponse:
    def test_success_response(self):
        resp = RPCResponse(id="resp-1", request_id="req-1", result=100)
        assert resp.result == 100
        assert resp.error is None

    def test_error_response(self):
        resp = RPCResponse(
            id="resp-2",
            request_id="req-2",
            error="Method not found",
            error_type="KeyError",
        )
        assert resp.error == "Method not found"
        assert resp.error_type == "KeyError"
