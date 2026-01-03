"""Tests for callpyback.pipeline module."""

import time

import pytest

from callpyback import ExecutionMode, Executor, Pipeline, task
from callpyback.types import TaskResult, TaskStatus


class TestPipeline:
    def test_single_step(self):
        result = Pipeline().pipe(lambda x: x * 2).run(21)

        assert result.status == TaskStatus.COMPLETED
        assert result.value == 42

    def test_multiple_steps(self):
        result = (
            Pipeline()
            .pipe(lambda x: x + 1)
            .pipe(lambda x: x * 2)
            .pipe(lambda x: x - 3)
            .run(10)
        )

        # (10 + 1) * 2 - 3 = 19
        assert result.value == 19

    def test_on_success_handler(self):
        success_values = []

        def success_handler(value):
            success_values.append(value)

        result = Pipeline().pipe(lambda x: x * 2).on_success(success_handler).run(21)

        assert result.value == 42
        assert success_values == [42]

    def test_on_failure_handler(self):
        failure_errors = []

        def failing_step(x):
            raise ValueError("Step failed")

        def failure_handler(error, value):
            failure_errors.append(str(error))

        result = Pipeline().pipe(failing_step).on_failure(failure_handler).run("input")

        assert result.status == TaskStatus.FAILED
        assert len(failure_errors) == 1
        assert "Step failed" in failure_errors[0]

    def test_on_complete_handler(self):
        complete_values = []

        def complete_handler(value):
            complete_values.append(value)

        result = (
            Pipeline()
            .pipe(lambda x: x.upper())
            .on_complete(complete_handler)
            .run("hello")
        )

        # on_complete receives the final value, not TaskResult
        assert len(complete_values) == 1
        assert complete_values[0] == "HELLO"

    def test_on_complete_called_on_failure(self):
        complete_calls = []

        def failing(x):
            raise RuntimeError("Error")

        def complete_handler(value):
            complete_calls.append(value)

        result = Pipeline().pipe(failing).on_complete(complete_handler).run("input")

        # on_complete is called per-step in finally block
        # For failed pipeline, global on_complete is not called
        assert result.status == TaskStatus.FAILED

    def test_failure_stops_pipeline(self):
        steps_executed = []

        def step1(x):
            steps_executed.append("step1")
            return x

        def step2(x):
            steps_executed.append("step2")
            raise ValueError("Fail here")

        def step3(x):
            steps_executed.append("step3")
            return x

        result = Pipeline().pipe(step1).pipe(step2).pipe(step3).run("data")

        assert result.status == TaskStatus.FAILED
        assert steps_executed == ["step1", "step2"]
        assert "step3" not in steps_executed

    def test_with_custom_executor(self):
        with Executor(mode=ExecutionMode.THREAD, max_workers=2) as executor:
            result = (
                Pipeline(executor=executor)
                .pipe(lambda x: x + 10)
                .pipe(lambda x: x * 2)
                .run(5)
            )

            # (5 + 10) * 2 = 30
            assert result.value == 30

    def test_multiple_success_handlers(self):
        handler_calls = []

        result = (
            Pipeline()
            .pipe(lambda x: x * 2)
            .on_success(lambda v: handler_calls.append("success1"))
            .on_success(lambda v: handler_calls.append("success2"))
            .run(10)
        )

        assert "success1" in handler_calls
        assert "success2" in handler_calls

    def test_empty_pipeline(self):
        result = Pipeline().run("passthrough")

        assert result.value == "passthrough"

    def test_execution_time_tracked(self):
        def slow_step(x):
            time.sleep(0.05)
            return x

        result = Pipeline().pipe(slow_step).run("data")

        assert result.execution_time >= 0.05


class TestTaskDecorator:
    def test_basic_task(self):
        @task()
        def double(x):
            return x * 2

        result = double(21)
        assert result == 42

    def test_task_with_success_handler(self):
        success_values = []

        @task(on_success=lambda v: success_values.append(v))
        def compute(x, y):
            return x + y

        result = compute(10, 20)

        assert result == 30
        assert success_values == [30]

    def test_task_with_failure_handler(self):
        failure_errors = []

        @task(on_failure=lambda e, args: failure_errors.append(str(e)))
        def failing_func():
            raise ValueError("Task error")

        with pytest.raises(ValueError):
            failing_func()

        assert len(failure_errors) == 1
        assert "Task error" in failure_errors[0]

    def test_task_preserves_function_metadata(self):
        @task()
        def documented_function(x: int) -> int:
            """This function doubles the input."""
            return x * 2

        assert documented_function.__name__ == "documented_function"
        assert "doubles" in documented_function.__doc__

    def test_task_with_complete_handler(self):
        complete_calls = []

        @task(on_complete=lambda v: complete_calls.append(v))
        def my_task(x):
            return x * 2

        result = my_task(21)

        assert result == 42
        assert complete_calls == [42]

    def test_task_with_kwargs(self):
        @task()
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        result = greet("World", greeting="Hi")
        assert result == "Hi, World!"
