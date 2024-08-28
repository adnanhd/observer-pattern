import threading
from collections import defaultdict
from typing import Dict, Any, TypeVar, Generic

T = TypeVar("T")
class SharedVar(Generic[T]):
    def __init__(self, initial_value: T):
        self._value = initial_value
        self._lock = threading.Lock()

    def get(self) -> T:
        """Return the current value of the shared variable."""
        with self._lock:
            return self._value

    def set(self, new_value: T):
        """Set the shared variable to a new value."""
        with self._lock:
            self._value = new_value


class SharedContext:
    def __init__(self):
        self._value: Dict[str, Any] = dict()
        self._lock = threading.Lock()

    def get(self, name: str):
        """Return the current value of the shared variable."""
        with self._lock:
            return self._value[name]

    def set(self, name: str, value: Any):
        """Set the shared variable to a new value."""
        with self._lock:
            self._value[name] = value
