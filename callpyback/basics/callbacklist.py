from functools import partial
import threading
import warnings
import inspect
from typing import Callable, Iterable, List, Dict, Any, Set, Optional, Type
from .scheduling import Policy, ThreadingPolicy, SinglePolicy
from .reduction import Reduction


class CallbackList:
    def __init__(
        self,
        policy: Policy = ThreadingPolicy(),
        reduction: Optional[Reduction] = None,
        allowed_parameters: Set[str] = set(),
    ):
        """Initializes a list of callback functions with threading support.

        Args:
            policy (Policy): The policy that dictates how callbacks are executed.
            allowed_parameters (Set[str]): A set of allowed parameters that callbacks can accept.
        """
        self.callbacks: Set[Callable] = set()
        self.allowed_parameters = allowed_parameters
        self.reducer = reduction
        self.scheduler = policy
        self._ready: bool = True
        self._lock = threading.RLock()  # Add a reentrant lock for thread safety

    def __repr__(self) -> str:
        repr_extra = ", ".join(map(str, self.callbacks))
        return f"{self.__class__.__name__}({repr_extra})"

    def __iter__(self) -> Iterable[Callable]:
        yield from self.callbacks

    def __len__(self) -> int:
        return len(self.callbacks)

    def __call__(self, *args: Any, **kwds: Any) -> Any:
        return self.add_callback(*args, **kwds)

    def add_callback(self, callback: Callable) -> Callable:
        """Adds a callback to the list after validating it.

        Args:
            callback (Callable): The callback function to be added.

        Returns:
            Callable: The added callback function.
        """
        with self._lock:
            self.validate_callback(callback)
            self.callbacks.add(callback)
        return callback

    def remove_callback(self, callback: Callable) -> Callable:
        """Removes a callback from the list.

        Args:
            callback (Callable): The callback function to be removed.

        Returns:
            Callable: The removed callback function.
        """
        with self._lock:
            self.callbacks.remove(callback)
        return callback

    def run_callbacks(self, **kwds: Any) -> None:
        """Runs all registered callbacks with the provided keyword arguments.

        Args:
            kwds (dict): The keyword arguments to pass to each callback.
        """
        with self._lock:
            if self._ready:
                self.scheduler.prepare_callbacks(list(self.callbacks), **kwds)
                self.scheduler.start()
                self._ready = False
            else:
                warnings.warn(
                    "Callbacks are already running. Please join the running callbacks first.",
                    RuntimeWarning,
                )

    def join_callbacks(self) -> None:
        """Waits until the execution of the runned callbacks finishes."""
        with self._lock:
            if not self._ready:
                self.scheduler.join()
                self._ready = True
            else:
                warnings.warn(
                    "No callbacks are currently running. Please run the callbacks first.",
                    RuntimeWarning,
                )

    def validate_callbacks(self) -> None:
        """Validates all registered callbacks."""
        with self._lock:
            for callback in self.callbacks:
                self.validate_callback(callback)

    def validate_callback(self, callback: Callable) -> None:
        """Validates a single callback.

        Ensures the callback is callable, is not an async coroutine, and has valid parameters.

        Args:
            callback (Callable): The callback function to validate.

        Raises:
            TypeError: If the callback is not a callable or is an async coroutine.
            AssertionError: If the callback has invalid parameters.
        """
        if not callable(callback):
            raise TypeError("Callback must be a callable.")
        if inspect.iscoroutinefunction(callback):
            raise TypeError(f"Callback `{callback.__name__}` cannot be a coroutine.")
        self.validate_callback_parameters(callback)

    def validate_callback_parameters(self, callback: Callable) -> None:
        """Validates the parameters accepted by the callback.

        Ensures that the callback only accepts parameters that are in the allowed list.

        Args:
            callback (Callable): The callback function to validate.

        Raises:
            AssertionError: If the callback has parameters not allowed by `allowed_parameters`.
        """
        found_params = set(inspect.signature(callback).parameters)
        if not found_params.issubset(self.allowed_parameters):
            raise AssertionError(
                f"Signature of callback `{callback.__name__}` is invalid.\n"
                f"Allowed parameters: {', '.join(self.allowed_parameters)}.\n"
                f"Found parameters: {', '.join(found_params)}."
            )
