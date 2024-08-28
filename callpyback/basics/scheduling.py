import sys
import inspect
from copy import deepcopy
from functools import partial
from abc import ABC, abstractmethod
from typing import Callable, List, Any, Dict, Tuple, Optional, Type, Union
from types import FrameType

ProfileFunction = Callable[[FrameType, str, Any], Any]
CallbackFunction = Callable[..., Any]
ExceptionTuple = Union[Tuple[Type[BaseException], ...], Type[BaseException]]


def get_callback_kwargs(
    callback: CallbackFunction, kwargs: Dict[str, Any]
) -> Dict[str, Any]:
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
    exceptions: Optional[ExceptionTuple]
    tracer: Optional[ProfileFunction]

    def __init__(
        self,
        exceptions: Optional[ExceptionTuple] = None,
        tracer: Optional[ProfileFunction] = None,
    ):
        self._names = list()
        self._localvars = dict()
        self._returnvars = dict()
        self.exceptions = exceptions
        self.tracer = tracer

    # def tracer(self, frame, event, arg):
    #     if event == "return":  # and frame.f_code.co_name in self._names:
    #         self._localvars[frame.f_code.co_name] = frame.f_locals.copy()
    #         self._returnvars[frame.f_code.co_name] = deepcopy(arg)

    @abstractmethod
    def prepare_callbacks(
        self, callbacks: List[CallbackFunction], **kwargs: Any
    ) -> None:
        """Prepare the callbacks according to the policy."""

    def start(self) -> None:
        if self.exceptions is not None:
            try:
                self._set_trace_profiler(self.tracer)
                self._start()
            except self.exceptions as e:
                self._set_trace_profiler(None)
                raise e
        else:
            self._set_trace_profiler(self.tracer)
            self._start()

    def join(self) -> None:
        self._join()
        self._set_trace_profiler(None)

    @abstractmethod
    def _start(self) -> None:
        """Start the execution of prepared callbacks."""

    @abstractmethod
    def _set_trace_profiler(self, tracer: Union[ProfileFunction, None]) -> None:
        """Set the tracer profile for reduction of callback-local parameters."""

    @abstractmethod
    def _join(self) -> None:
        """Wait for all the started callbacks to complete."""


class SinglePolicy(Policy):
    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.callbacks = []

    def prepare_callbacks(self, callbacks: List[CallbackFunction], **kwargs: Any):
        """Prepares the callbacks for execution by storing them."""
        self.callbacks = [
            (callback, get_callback_kwargs(callback, kwargs)) for callback in callbacks
        ]

    def _start(self) -> None:
        """Executes the callbacks sequentially."""
        for callback, kwargs in self.callbacks:
            callback(**kwargs)

    def _join(self) -> None:
        """No-op for SinglePolicy since everything runs sequentially."""

    def _set_trace_profiler(self, tracer: Union[ProfileFunction, None]) -> None:
        sys.setprofile(tracer)


import threading


class ExceptionThread(threading.Thread):
    def __init__(self, exceptions: Optional[ExceptionTuple] = None, **kwds):
        assert exceptions is None or (
            isinstance(exceptions, tuple)
            and all(map(BaseException.__subclasscheck__, exceptions))
            or issubclass(exceptions, BaseException)
        ), "exceptions must be a tuple of exceptions"
        self._exceptions = exceptions
        super().__init__(**kwds)

    def run(self):
        self.exc = None
        if self._exceptions is not None:
            try:
                threading.Thread.run(self)
            except self._exceptions as e:
                self.exc = e
        else:
            threading.Thread.run(self)

    def join(self, timeout: Union[float, None] = None):
        threading.Thread.join(self, timeout)
        if self.exc:
            raise self.exc


class ThreadingPolicy(Policy):
    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.threads = []

    def prepare_callbacks(
        self, callbacks: List[CallbackFunction], **kwargs: Any
    ) -> None:
        """Prepares the threads but does not start them."""
        self.threads = [
            ExceptionThread(
                target=callback,
                kwargs=get_callback_kwargs(callback=callback, kwargs=kwargs),
                exceptions=self.exceptions,
            )
            for callback in callbacks
        ]

    def _start(self) -> None:
        """Starts all the prepared threads."""
        for thread in self.threads:
            thread.start()

    def _join(self) -> None:
        """Waits for all the threads to complete."""
        for thread in self.threads:
            thread.join()

    def _set_trace_profiler(self, tracer:Union[ProfileFunction, None]) -> None:
        threading.setprofile(tracer)


import multiprocessing


class MultiprocessingPolicy(Policy):
    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.processes = []

    def prepare_callbacks(
        self, callbacks: List[CallbackFunction], **kwargs: Any
    ) -> None:
        """Prepares the processes but does not start them."""
        self.processes = [
            multiprocessing.Process(
                target=callback,
                kwargs=get_callback_kwargs(callback=callback, kwargs=kwargs),
            )
            for callback in callbacks
        ]

    def _start(self) -> None:
        """Starts all the prepared processes."""
        for process in self.processes:
            process.start()

    def _join(self) -> None:
        """Waits for all the processes to complete."""
        for process in self.processes:
            process.join()
