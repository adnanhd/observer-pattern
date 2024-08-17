"""Module containing BaseCallBackMixin implementation"""

import inspect
import threading
from typing import Callable, Any, Dict, Iterable, List, Tuple

from callpyback.basics.callbacklist import CallbackList

CALLBACK_LABELS = ("on_call", "on_success", "on_failure", "on_end")
CALLBACK_PARAMETER_MAP = {
    "on_call": {"func", "func_kwargs"},
    "on_success": {"func", "func_result", "func_kwargs"},
    "on_failure": {"func", "func_exception", "func_kwargs"},
    "on_end": {
        "func",
        "func_result",
        "func_exception",
        "func_kwargs",
        "func_scope_vars",
    },
}


class BaseCallBackMixin:
    """Class implementing basic callback features.

    Attributes:
        N/A

    Methods:
        validate_callbacks():
            Validates callbacks passed to class constructor.
        run_callback_func(func, func_kwargs):
            Executes given callback function with given kwargs.
        run_on_call_func(func, func_args, func_kwargs):
            Generates kwargs for given `on_call` callback function and executes
            it with generated kwargs.
        run_on_success_func(func, func_result, func_args, func_kwargs):
            Generates kwargs for given `on_success` callback function and
            executes it with generated kwargs.
        run_on_failure_func(func, func_exception, func_args, func_kwargs):
            Generates kwargs for given `on_failure` callback function and
            executes it with generated kwargs.
        run_on_end_func(func, func_result, func_exception, func_args,
        func_kwargs, func_scope_vars):
            Generates kwargs for given `on_end` callback function and executes
            it with generated kwargs.
        get_callback_kwargs(callback, **kwargs):
            Generates kwargs for given callback function.

    """

    def __init__(
        self,
        **kwargs,
    ):
        """Class constructor. Sets instance variables.

        Args:
            on_call (Callable, optional): Called before execution.
                Defaults to DEFAULT_ON_CALL_LAMBDA.
            on_success (Callable, optional): Called after success.
                Defaults to DEFAULT_ON_SUCCESS_LAMBDA.
            on_failure (Callable, optional): Called after failed execution.
                Defaults to DEFAULT_ON_FAILURE_LAMBDA.
            on_end (Callable, optional): Called after execution.
                Defaults to DEFAULT_ON_END_LAMBDA.

        Returns:
            BaseCallBackMixin: mixin instance
        Raises:
            N/A
        """
        super().__init__(**kwargs)
        self.on_call = CallbackList(allowed_parameters={"func", "func_kwargs"})
        self.on_success = CallbackList(
            allowed_parameters={"func", "func_result", "func_kwargs"},
        )
        self.on_failure = CallbackList(
            allowed_parameters={"func", "func_exception", "func_kwargs"},
        )
        self.on_end = CallbackList(
            allowed_parameters={
                "func",
                "func_result",
                "func_exception",
                "func_kwargs",
                "func_scope_vars",
            },
        )
        self.callbacks = (self.on_call, self.on_success, self.on_failure, self.on_end)

    def validate_callbacks(self):
        """Validates callbacks passed to class constructor.

        Executes following checks:
            1. Callback must be a Callable type.
            2. Callback cannot be an async coroutine.
            3. Callback must accepted some or none of the parameters specified
               in CALLBACK_PARAMETER_MAP.

        Args:
            N/A
        Returns:
            None
        Raises:
            TypeError: Raised if one of the callbacks is not Callable.
            TypeError: Raised if one of the callbacks is an async coroutine.
            AssertionError: Raised if any callbacks haves invalid parameters.
        """
        self.on_end.validate_callbacks()
        self.on_success.validate_callbacks()
        self.on_failure.validate_callbacks()
        self.on_call.validate_callbacks()

    def join_callback_funcs(self):
        self.on_end.join_callbacks()
        self.on_success.join_callbacks()
        self.on_failure.join_callbacks()
        self.on_call.join_callbacks()

    def run_on_call_func(self, func, func_kwargs):
        """Generates kwargs for given `on_call` callback function and executes
        it with generated kwargs.

        Args:
            func (func): decorated function
            func_kwargs (dict): Keyword arguments for the decorated function.
        Returns:
            None
        Raises:
            N/A
        """
        self.on_call.run_callbacks(func=func, func_kwargs=func_kwargs)

    def run_on_success_func(self, func, func_result, func_kwargs):
        """Generates kwargs for given `on_success` callback function and
        executes it with generated kwargs.

        Args:
            func (func): decorated function
            func_result (Any): Result of the decorated function.
            func_kwargs (dict): Keyword arguments for the decorated function.
        Returns:
            None
        Raises:
            N/A
        """
        self.on_success.run_callbacks(
            func=func,
            func_result=func_result,
            func_kwargs=func_kwargs,
        )

    def run_on_failure_func(self, func, func_exception, func_kwargs):
        """Generates kwargs for given `on_failure` callback function and
        executes it with generated kwargs.

        Args:
            func (func): decorated function
            func_exception (Exception): Exception raised by decorated function.
            func_kwargs (dict): Keyword arguments for the decorated function.
        Returns:
            None
        Raises:
            N/A
        """
        self.on_failure.run_callbacks(
            func=func,
            func_exception=func_exception,
            func_kwargs=func_kwargs,
        )

    def run_on_end_func(
        self, func, func_result, func_exception, func_kwargs, func_scope_vars
    ):
        """Generates kwargs for given `on_end` callback function and executes
        it with generated kwargs.

        Args:
            func (func): decorated function
            func_result (Any): Result of the decorated function.
            func_exception (Exception): Exception raised by decorated function.
            func_kwargs (dict): Keyword arguments for the decorated function.
            func_scope_vars (dict): Scope variables for the decorated function.
        Returns:
            None
        Raises:
            N/A
        """
        self.on_end.run_callbacks(
            func=func,
            func_result=func_result,
            func_exception=func_exception,
            func_kwargs=func_kwargs,
            func_scope_vars=func_scope_vars,
        )
