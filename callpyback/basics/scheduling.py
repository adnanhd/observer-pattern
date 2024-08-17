import sys
import inspect
from copy import deepcopy
from functools import partial
from abc import ABC, abstractmethod
from typing import Callable, List, Any, Dict


def get_callback_kwargs(callback: Callable, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Generates kwargs for the given callback function.

    Only kwargs specified in the callback signature will be passed to the callback.
    This allows omitting unused parameters in user-created callbacks.

    Args:
        callback (Callable): The callback function to extract parameters for.
        kwargs (dict): The full dictionary of keyword arguments.

    Returns:
        dict: Filtered dictionary of keyword arguments suitable for the callback.
    """
    return {
        kwarg_name: kwarg_value
        for kwarg_name, kwarg_value in kwargs.items()
        if kwarg_name in inspect.signature(callback).parameters
    }


class Policy(ABC):
    def __init__(self):
        self._names = list()
        self._localvars = dict()
        self._returnvars = dict()

    # def tracer(self, frame, event, arg):
    #     if event == "return":  # and frame.f_code.co_name in self._names:
    #         self._localvars[frame.f_code.co_name] = frame.f_locals.copy()
    #         self._returnvars[frame.f_code.co_name] = deepcopy(arg)

    @abstractmethod
    def prepare_callbacks(self, callbacks: List[Callable], **kwargs: Any) -> None:
        """Prepare the callbacks according to the policy."""

    @abstractmethod
    def start(self) -> None:
        """Start the execution of prepared callbacks."""

    @abstractmethod
    def join(self) -> None:
        """Wait for all the started callbacks to complete."""


class SinglePolicy(Policy):
    def __init__(self, tracer=None):
        self.callbacks = []
        self.tracer = tracer

    def prepare_callbacks(self, callbacks: List[Callable], **kwargs: Any):
        """Prepares the callbacks for execution by storing them."""
        self.callbacks = [
            (callback, get_callback_kwargs(callback, kwargs)) for callback in callbacks
        ]

    def start(self) -> None:
        """Executes the callbacks sequentially."""
        sys.setprofile(self.tracer)
        for callback, kwargs in self.callbacks:
            callback(**kwargs)
        sys.setprofile(None)

    def join(self) -> None:
        """No-op for SinglePolicy since everything runs sequentially."""


import threading


class ThreadingPolicy(Policy):
    def __init__(self, tracer=None):
        self.threads = []
        self.tracer = tracer

    def prepare_callbacks(self, callbacks: List[Callable], **kwargs: Any) -> None:
        """Prepares the threads but does not start them."""
        self.threads = [
            threading.Thread(
                target=callback,
                kwargs=get_callback_kwargs(callback=callback, kwargs=kwargs),
            )
            for callback in callbacks
        ]

    def start(self) -> None:
        """Starts all the prepared threads."""
        threading.setprofile(self.tracer)
        for thread in self.threads:
            thread.start()

    def join(self) -> None:
        """Waits for all the threads to complete."""
        for thread in self.threads:
            thread.join()
        threading.setprofile(None)


import multiprocessing


class MultiprocessingPolicy(Policy):
    def __init__(self):
        self.processes = []

    def prepare_callbacks(self, callbacks: List[Callable], **kwargs: Any) -> None:
        """Prepares the processes but does not start them."""
        self.processes = [
            multiprocessing.Process(
                target=callback,
                kwargs=get_callback_kwargs(callback=callback, kwargs=kwargs),
            )
            for callback in callbacks
        ]

    def start(self) -> None:
        """Starts all the prepared processes."""
        for process in self.processes:
            process.start()

    def join(self) -> None:
        """Waits for all the processes to complete."""
        for process in self.processes:
            process.join()
