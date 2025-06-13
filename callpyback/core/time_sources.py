"""Time source implementations."""

import time


class SystemTimeSource:
    """System time source using time.time()."""

    def now(self) -> float:
        return time.time()


class MockTimeSource:
    """Mock time source for testing."""

    def __init__(self, initial_time: float = 0.0):
        self._time = initial_time

    def now(self) -> float:
        return self._time

    def advance(self, seconds: float) -> None:
        """Advance time by specified seconds."""
        self._time += seconds

    def set_time(self, timestamp: float) -> None:
        """Set absolute time."""
        self._time = timestamp
