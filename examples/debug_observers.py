#!/usr/bin/env python3
"""Debug why observers aren't being called."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "."))

from callpyback import CallPyBack, on_success, on_failure, on_completion
from callpyback.core.state_machine import ExecutionState


def debug_observer_registration():
    """Debug observer registration."""
    print("=== Debugging Observer Registration ===")

    calls = []

    def test_callback(context):
        calls.append(f"Observer called with state: {context.state.name}")
        print(f"🎯 Observer callback triggered! State: {context.state.name}")

    # Create decorator and manually inspect it
    decorator = CallPyBack(
        observers=[on_success(test_callback)], default_return="test_default"
    )

    print(f"Decorator created. Observer manager: {decorator._observer_manager}")
    print(f"Observer count: {decorator._observer_manager.get_observer_count()}")

    # Check what observers are registered
    observers = decorator._observer_manager.get_observers_for_state(
        ExecutionState.POST_SUCCESS
    )
    print(f"Observers for POST_SUCCESS: {len(observers)}")
    for i, obs in enumerate(observers):
        print(f"  Observer {i}: {obs}, priority: {obs.priority}")

    @decorator
    def test_function():
        return "success"

    print("Calling decorated function...")
    result = test_function()
    print(f"Function result: {result}")
    print(f"Observer calls: {calls}")


def debug_callback_observer():
    """Debug the CallbackObserver directly."""
    print("\n=== Debugging CallbackObserver Directly ===")

    from callpyback.observers.callback import CallbackObserver
    from callpyback.core.context import (
        ExecutionContext,
        FunctionSignature,
        ExecutionResult,
    )
    from callpyback.core.state_machine import ExecutionState

    calls = []

    def test_callback(context):
        calls.append("Direct observer called")
        print(f"🎯 Direct observer called! State: {context.state.name}")

    # Create observer directly
    observer = CallbackObserver(
        callback=test_callback, interested_states={ExecutionState.POST_SUCCESS}
    )

    # Create test context
    sig = FunctionSignature("test_func", "test_module", ())
    result = ExecutionResult("test_result", 0.001)
    context = ExecutionContext(
        function_signature=sig,
        arguments={},
        state=ExecutionState.POST_SUCCESS,
        result=result,
    )

    print("Calling observer directly...")
    observer.update(context)
    print(f"Direct observer calls: {calls}")


def debug_factory_functions():
    """Debug the factory functions."""
    print("\n=== Debugging Factory Functions ===")

    def test_callback(result):
        print(f"🎯 Factory observer called! Result: {result}")

    observer = on_success(test_callback)
    print(f"Factory observer created: {observer}")
    print(f"Observer type: {type(observer)}")
    print(f"Observer priority: {observer.priority}")
    print(f"Observer interested states: {observer._interested_states}")


def debug_observer_manager():
    """Debug the observer manager."""
    print("\n=== Debugging Observer Manager ===")

    from callpyback.management.observer_manager import ErrorIsolatingObserverManager
    from callpyback.observers.callback import CallbackObserver
    from callpyback.core.state_machine import ExecutionState

    calls = []

    def test_callback(context):
        calls.append("Manager test")
        print(f"🎯 Manager observer called! State: {context.state.name}")

    manager = ErrorIsolatingObserverManager()
    observer = CallbackObserver(test_callback, {ExecutionState.POST_SUCCESS})

    manager.add_observer(observer, states={ExecutionState.POST_SUCCESS})

    print(f"Observer manager created")
    print(f"Total observers: {manager.get_observer_count()}")

    observers = manager.get_observers_for_state(ExecutionState.POST_SUCCESS)
    print(f"Observers for POST_SUCCESS: {len(observers)}")

    # Create test context and notify
    from callpyback.core.context import (
        ExecutionContext,
        FunctionSignature,
        ExecutionResult,
    )

    sig = FunctionSignature("test_func", "test_module", ())
    result = ExecutionResult("test_result", 0.001)
    context = ExecutionContext(
        function_signature=sig,
        arguments={},
        state=ExecutionState.POST_SUCCESS,
        result=result,
    )

    print("Notifying observers...")
    manager.notify_observers(context)
    print(f"Manager observer calls: {calls}")


if __name__ == "__main__":
    debug_observer_registration()
    debug_callback_observer()
    debug_factory_functions()
    debug_observer_manager()
