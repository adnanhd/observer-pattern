#!/usr/bin/env python3
"""Absolutely minimal test to see what works."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "."))

from callpyback import CallPyBack


def minimal_test():
    """Most basic test possible."""
    print("=== Minimal Test ===")

    # Test 1: No observers at all
    @CallPyBack()
    def basic_function():
        return "basic_result"

    result = basic_function()
    print(f"Test 1 - No observers: {result}")

    # Test 2: Direct callback (no factory)
    from callpyback.observers.callback import CallbackObserver
    from callpyback.core.state_machine import ExecutionState

    def direct_callback(context):
        print(f"🎯 DIRECT CALLBACK WORKED! State: {context.state.name}")

    direct_observer = CallbackObserver(
        callback=direct_callback, interested_states={ExecutionState.COMPLETED}
    )

    @CallPyBack(observers=[direct_observer])
    def direct_function():
        return "direct_result"

    print("Test 2 - Direct observer:")
    result = direct_function()
    print(f"Result: {result}")

    # Test 3: Factory function
    from callpyback import on_completion

    def factory_callback(context):
        print(f"🎯 FACTORY CALLBACK WORKED! State: {context.state.name}")

    factory_observer = on_completion(factory_callback)

    @CallPyBack(observers=[factory_observer])
    def factory_function():
        return "factory_result"

    print("Test 3 - Factory observer:")
    result = factory_function()
    print(f"Result: {result}")


if __name__ == "__main__":
    minimal_test()
