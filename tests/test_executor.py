"""Tests for eventforge.executor module."""

import time

import pytest

from eventforge import ExecutionMode, Executor
from eventforge.types import TaskStatus


def slow_task(duration):
    time.sleep(duration)
    return f"slept {duration}s"


def compute_sum(n):
    return sum(range(n))


def failing_task():
    raise ValueError("Intentional error")


class TestExecutorSequential:
    def test_submit_and_result(self):
        with Executor(mode=ExecutionMode.SEQUENTIAL) as executor:
            task_id = executor.submit(lambda x: x * 2, 21)
            result = executor.result(task_id)

            assert result.status == TaskStatus.COMPLETED
            assert result.value == 42

    def test_submit_multiple(self):
        with Executor(mode=ExecutionMode.SEQUENTIAL) as executor:
            task_ids = [executor.submit(compute_sum, n) for n in [10, 100, 1000]]

            results = [executor.result(tid) for tid in task_ids]

            assert all(r.status == TaskStatus.COMPLETED for r in results)
            assert results[0].value == 45  # sum(0..9)
            assert results[1].value == 4950  # sum(0..99)

    def test_task_failure(self):
        with Executor(mode=ExecutionMode.SEQUENTIAL) as executor:
            task_id = executor.submit(failing_task)
            result = executor.result(task_id)

            assert result.status == TaskStatus.FAILED
            assert "Intentional error" in result.error
            assert result.error_type == "ValueError"

    def test_map(self):
        with Executor(mode=ExecutionMode.SEQUENTIAL) as executor:
            results = executor.map(lambda x: x**2, [1, 2, 3, 4, 5])

            values = [r.value for r in results]
            assert values == [1, 4, 9, 16, 25]

    def test_is_success_property(self):
        with Executor(mode=ExecutionMode.SEQUENTIAL) as executor:
            task_id = executor.submit(lambda: 42)
            result = executor.result(task_id)

            assert result.is_success is True
            assert result.is_failure is False

    def test_is_failure_property(self):
        with Executor(mode=ExecutionMode.SEQUENTIAL) as executor:
            task_id = executor.submit(failing_task)
            result = executor.result(task_id)

            assert result.is_success is False
            assert result.is_failure is True


class TestExecutorThread:
    def test_concurrent_execution(self):
        with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
            start = time.time()

            task_ids = [executor.submit(slow_task, 0.1) for _ in range(4)]

            results = [executor.result(tid) for tid in task_ids]
            elapsed = time.time() - start

            assert all(r.status == TaskStatus.COMPLETED for r in results)
            # Should complete in ~0.1s (parallel) not 0.4s (sequential)
            assert elapsed < 0.3

    def test_result_timeout(self):
        with Executor(mode=ExecutionMode.THREAD) as executor:
            task_id = executor.submit(slow_task, 10.0)

            with pytest.raises(TimeoutError):
                executor.result(task_id, timeout=0.1)

    def test_thread_map(self):
        with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
            results = executor.map(lambda x: x * 2, [1, 2, 3, 4])

            values = [r.value for r in results]
            assert values == [2, 4, 6, 8]


class TestExecutorProcess:
    def test_process_execution(self):
        with Executor(mode=ExecutionMode.PROCESS, max_workers=2) as executor:
            task_id = executor.submit(compute_sum, 10000)
            result = executor.result(task_id, timeout=10.0)

            assert result.status == TaskStatus.COMPLETED
            assert result.value == sum(range(10000))

    def test_process_map(self):
        with Executor(mode=ExecutionMode.PROCESS, max_workers=2) as executor:
            results = executor.map(compute_sum, [100, 200, 300])

            assert all(r.status == TaskStatus.COMPLETED for r in results)
            assert results[0].value == sum(range(100))
            assert results[1].value == sum(range(200))
            assert results[2].value == sum(range(300))


class TestExecutorContextManager:
    def test_context_manager_starts_and_stops(self):
        executor = Executor(mode=ExecutionMode.THREAD)
        assert executor._running is False

        with executor:
            assert executor._running is True

        assert executor._running is False

    def test_mode_property(self):
        executor = Executor(mode=ExecutionMode.PROCESS)
        assert executor.mode == ExecutionMode.PROCESS
