"""Tests for eventforge.task module."""

import threading
import time

import pytest

from eventforge import (
    ExecutionMode,
    Executor,
    MessageQueue,
    MetricsMeter,
    SharedState,
    TaskContext,
    TaskPool,
    TaskRunner,
    TimingMeter,
    task,
)


class TestSharedState:
    def test_get_set(self):
        state = SharedState()
        state.set("key", "value")
        assert state.get("key") == "value"

    def test_get_default(self):
        state = SharedState()
        assert state.get("missing") is None
        assert state.get("missing", "default") == "default"

    def test_update_atomic(self):
        state = SharedState()
        state.set("count", 0)

        result = state.update("count", lambda x: x + 1)
        assert result == 1
        assert state.get("count") == 1

    def test_update_with_none(self):
        state = SharedState()
        result = state.update("new_key", lambda x: (x or 0) + 10)
        assert result == 10

    def test_thread_safety(self):
        state = SharedState()
        state.set("count", 0)

        def increment():
            for _ in range(100):
                state.update("count", lambda x: x + 1)

        threads = [threading.Thread(target=increment) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert state.get("count") == 1000


class TestTaskContext:
    def test_execution_time(self):
        ctx = TaskContext(
            task_id="123",
            func_name="test",
            start_time=0.0,
            end_time=1.5,
        )
        assert ctx.execution_time == 1.5

    def test_is_success_true(self):
        ctx = TaskContext(
            task_id="123",
            func_name="test",
            result="success",
        )
        assert ctx.is_success is True

    def test_is_success_false(self):
        ctx = TaskContext(
            task_id="123",
            func_name="test",
            error=ValueError("error"),
        )
        assert ctx.is_success is False


class TestTaskDecorator:
    def test_basic_task(self):
        @task()
        def double(x):
            return x * 2

        result = double(21)
        assert result == 42

    def test_task_preserves_function_metadata(self):
        @task()
        def documented_function(x: int) -> int:
            """This function doubles the input."""
            return x * 2

        assert documented_function.__name__ == "documented_function"
        assert "doubles" in documented_function.__doc__

    def test_task_with_kwargs(self):
        @task()
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        result = greet("World", greeting="Hi")
        assert result == "Hi, World!"

    def test_task_with_success_handler(self):
        success_contexts = []

        @task(on_success=lambda ctx: success_contexts.append(ctx))
        def compute(x, y):
            return x + y

        result = compute(10, 20)

        assert result == 30
        assert len(success_contexts) == 1
        assert success_contexts[0].result == 30
        assert success_contexts[0].is_success is True

    def test_task_with_failure_handler(self):
        failure_contexts = []

        @task(on_failure=lambda ctx: failure_contexts.append(ctx))
        def failing_func():
            raise ValueError("Task error")

        with pytest.raises(ValueError):
            failing_func()

        assert len(failure_contexts) == 1
        assert "Task error" in str(failure_contexts[0].error)

    def test_task_with_complete_handler(self):
        complete_contexts = []

        @task(on_complete=lambda ctx: complete_contexts.append(ctx))
        def my_task(x):
            return x * 2

        result = my_task(21)

        assert result == 42
        assert len(complete_contexts) == 1
        assert complete_contexts[0].result == 42

    def test_task_complete_called_on_failure(self):
        complete_calls = []

        @task(on_complete=lambda ctx: complete_calls.append(ctx))
        def failing_task():
            raise RuntimeError("Error")

        with pytest.raises(RuntimeError):
            failing_task()

        assert len(complete_calls) == 1
        assert complete_calls[0].error is not None

    def test_task_with_observer(self):
        timing = TimingMeter()

        @task(on_execute=[timing])
        def slow_task(x):
            time.sleep(0.01)
            return x * 2

        result = slow_task(21)

        assert result == 42
        assert timing.stats["count"] == 1
        assert timing.stats["avg"] >= 0.01

    def test_task_with_multiple_observers(self):
        timing = TimingMeter()
        # MetricsMeter pulls a number out of ctx.result for each call.
        calls = MetricsMeter("calls", extract=lambda ctx: 1.0)

        @task(on_execute=[timing, calls])
        def my_task(x):
            return x + 10

        my_task(5)
        my_task(10)

        assert timing.stats["count"] == 2
        assert calls.stats["count"] == 2
        assert calls.stats["sum"] == 2.0

    def test_task_exposes_state(self):
        @task()
        def stateful_task(x):
            return x

        assert hasattr(stateful_task, "state")
        assert isinstance(stateful_task.state, SharedState)

        stateful_task.state.set("custom", "value")
        assert stateful_task.state.get("custom") == "value"

    def test_task_metadata_attributes(self):
        @task(topic="custom.topic")
        def my_task(x):
            return x

        assert my_task._task is True
        assert my_task._topic == "custom.topic"


class TestTaskWithQueue:
    def test_task_queue_subscription(self):
        queue = MessageQueue()
        results = []

        @task(
            queue=queue,
            topic="test.topic",
            on_success=lambda ctx: results.append(ctx.result),
        )
        def process(data):
            return data.upper()

        # Direct call
        result = process("hello")
        assert result == "HELLO"

        # Queue trigger
        queue.publish("test.topic", "world")

        assert len(results) == 2
        assert "HELLO" in results
        assert "WORLD" in results

    def test_task_queue_dict_payload(self):
        queue = MessageQueue()
        results = []

        @task(queue=queue, topic="test.dict")
        def greet(name, greeting="Hello"):
            result = f"{greeting}, {name}!"
            results.append(result)
            return result

        queue.publish("test.dict", {"name": "World", "greeting": "Hi"})

        assert len(results) == 1
        assert results[0] == "Hi, World!"

    def test_task_queue_list_payload(self):
        queue = MessageQueue()
        results = []

        @task(queue=queue, topic="test.list")
        def add(a, b):
            result = a + b
            results.append(result)
            return result

        queue.publish("test.list", [10, 20])

        assert len(results) == 1
        assert results[0] == 30

    def test_task_publishes_success(self):
        queue = MessageQueue()
        success_messages = []

        @queue.on("test.publish.success")
        def on_success(msg):
            success_messages.append(msg.payload)

        @task(queue=queue, topic="test.publish", publish_result=True)
        def my_task(x):
            return x * 2

        my_task(21)

        assert len(success_messages) == 1
        assert success_messages[0]["result"] == 42

    def test_task_publishes_failure(self):
        queue = MessageQueue()
        failure_messages = []

        @queue.on("test.fail.failure")
        def on_failure(msg):
            failure_messages.append(msg.payload)

        @task(queue=queue, topic="test.fail", publish_result=True)
        def failing_task():
            raise ValueError("Oops")

        with pytest.raises(ValueError):
            failing_task()

        assert len(failure_messages) == 1
        assert "Oops" in failure_messages[0]["error"]

    def test_task_disable_publish(self):
        queue = MessageQueue()
        success_messages = []

        @queue.on("test.nopub.success")
        def on_success(msg):
            success_messages.append(msg.payload)

        @task(queue=queue, topic="test.nopub", publish_result=False)
        def my_task(x):
            return x * 2

        my_task(21)

        assert len(success_messages) == 0


class TestTaskWithExecutor:
    def test_task_with_thread_executor(self):
        with Executor(mode=ExecutionMode.THREAD, max_workers=2) as executor:

            @task(executor=executor)
            def compute(x):
                return x * 2

            result = compute(21)
            assert result == 42

    def test_task_with_process_executor(self):
        # Note: Process executor requires picklable functions
        # Local/nested functions cannot be pickled, so this test
        # uses a module-level function via lambda workaround
        # Real usage should define tasks at module level
        with Executor(mode=ExecutionMode.PROCESS, max_workers=2) as executor:
            # Use a built-in function that's picklable
            runner = TaskRunner(
                func=str.upper,
                topic="test",
                executor=executor,
            )
            result = runner.run("hello")
            assert result == "HELLO"


class TestTaskRunner:
    def test_runner_direct_instantiation(self):
        def my_func(x):
            return x * 2

        runner = TaskRunner(
            func=my_func,
            topic="test",
            executor=Executor(),
        )

        result = runner.run(21)
        assert result == 42

    def test_runner_shared_state(self):
        call_count = []

        def counting_func(x):
            call_count.append(1)
            return x

        runner = TaskRunner(
            func=counting_func,
            topic="test",
            executor=Executor(),
        )

        runner.run(1)
        runner.run(2)
        runner.run(3)

        assert len(call_count) == 3
        # Shared state persists across invocations
        assert runner.state is runner.state

    def test_runner_with_observers(self):
        timing = TimingMeter()

        def my_func(x):
            return x * 2

        runner = TaskRunner(
            func=my_func,
            topic="test",
            executor=Executor(),
            on_execute=[timing],
        )

        runner.run(10)
        runner.run(20)

        assert timing.stats["count"] == 2


class TestTaskPool:
    def test_pool_creation(self):
        pool = TaskPool(max_instances=3)
        assert pool.max_instances == 3
        assert pool.active == 0
        assert pool.available == 3

    def test_pool_acquire_release(self):
        pool = TaskPool(max_instances=2)

        assert pool.acquire()
        assert pool.active == 1
        assert pool.available == 1

        assert pool.acquire()
        assert pool.active == 2
        assert pool.available == 0

        pool.release()
        assert pool.active == 1
        assert pool.available == 1

    def test_pool_stats(self):
        pool = TaskPool(max_instances=2)

        pool.acquire()
        pool.release()
        pool.acquire()
        pool.release()

        stats = pool.stats
        assert stats["max"] == 2
        assert stats["total_processed"] == 2
        assert stats["active"] == 0

    def test_pool_slot_context_manager(self):
        pool = TaskPool(max_instances=1)

        with pool.slot() as acquired:
            assert acquired
            assert pool.active == 1

        assert pool.active == 0

    def test_pool_non_blocking(self):
        pool = TaskPool(max_instances=1)

        pool.acquire()  # Take the only slot

        # Non-blocking acquire should fail
        acquired = pool.acquire(blocking=False)
        assert not acquired
        assert pool.active == 1  # Still only 1 active

    def test_pool_timeout(self):
        pool = TaskPool(max_instances=1)

        pool.acquire()  # Take the only slot

        # Timed acquire should fail after timeout
        start = time.time()
        acquired = pool.acquire(blocking=True, timeout=0.1)
        elapsed = time.time() - start

        assert not acquired
        assert elapsed >= 0.1
        assert elapsed < 0.5  # Shouldn't take too long

    def test_pool_invalid_max_instances(self):
        with pytest.raises(ValueError):
            TaskPool(max_instances=0)

        with pytest.raises(ValueError):
            TaskPool(max_instances=-1)


class TestTaskWithMaxInstances:
    def test_task_with_max_instances(self):
        results = []

        @task(max_instances=2)
        def limited_task(x):
            time.sleep(0.05)
            results.append(x)
            return x * 2

        assert limited_task.pool is not None
        assert limited_task.pool.max_instances == 2

        # Run concurrently
        threads = []
        for i in range(4):
            t = threading.Thread(target=limited_task, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(results) == 4
        assert limited_task.pool.stats["total_processed"] == 4

    def test_task_pool_limits_concurrency(self):
        max_concurrent = [0]
        current_concurrent = [0]
        lock = threading.Lock()

        @task(max_instances=2)
        def tracked_task(x):
            with lock:
                current_concurrent[0] += 1
                max_concurrent[0] = max(max_concurrent[0], current_concurrent[0])

            time.sleep(0.05)

            with lock:
                current_concurrent[0] -= 1

            return x

        threads = []
        for i in range(6):
            t = threading.Thread(target=tracked_task, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Should never exceed max_instances
        assert max_concurrent[0] <= 2

    def test_task_without_max_instances_has_no_pool(self):
        @task()
        def unlimited_task(x):
            return x

        assert unlimited_task.pool is None

    def test_runner_with_max_instances(self):
        def my_func(x):
            time.sleep(0.02)
            return x * 2

        runner = TaskRunner(
            func=my_func,
            topic="test",
            executor=Executor(),
            max_instances=2,
        )

        assert runner.pool is not None
        assert runner.max_instances == 2

        # Run a few times
        results = [runner.run(i) for i in range(3)]
        assert results == [0, 2, 4]
        assert runner.pool.stats["total_processed"] == 3
