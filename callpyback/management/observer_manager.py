"""Observer management implementations."""

import logging
import threading
from collections import defaultdict
from weakref import WeakSet

from typing_compat import Dict, List, Optional, Set

from callpyback.core.context import ExecutionContext
from callpyback.core.state_machine import ExecutionPhase, ExecutionState
from callpyback.protocols import Observer


class ConcurrentObserverManager:
    """Thread-safe observer manager."""

    def __init__(self):
        self._observers: WeakSet[Observer] = WeakSet()
        self._state_observers: Dict[ExecutionState, List[Observer]] = defaultdict(list)
        self._phase_observers: Dict[ExecutionPhase, List[Observer]] = defaultdict(list)
        self._lock = threading.RLock()

    def add_observer(
        self,
        observer: Observer,
        states: Optional[Set[ExecutionState]] = None,
        phases: Optional[Set[ExecutionPhase]] = None,
    ) -> None:
        """Add observer for specific states/phases."""
        with self._lock:
            self._observers.add(observer)

            if states:
                for state in states:
                    self._state_observers[state].append(observer)

            if phases:
                for phase in phases:
                    self._phase_observers[phase].append(observer)

    def remove_observer(self, observer: Observer) -> None:
        """Remove observer from all collections."""
        with self._lock:
            self._observers.discard(observer)

            # Remove from state collections
            for state_list in self._state_observers.values():
                if observer in state_list:
                    state_list.remove(observer)

            # Remove from phase collections
            for phase_list in self._phase_observers.values():
                if observer in phase_list:
                    phase_list.remove(observer)

    def get_observers_for_state(self, state: ExecutionState) -> List[Observer]:
        """Get observers interested in specific state."""
        with self._lock:
            observers = self._state_observers.get(state, [])
            return sorted(observers, key=lambda obs: obs.priority, reverse=True)

    def get_observers_for_phase(self, phase: ExecutionPhase) -> List[Observer]:
        """Get observers interested in specific phase."""
        with self._lock:
            observers = self._phase_observers.get(phase, [])
            return sorted(observers, key=lambda obs: obs.priority, reverse=True)

    def notify_observers(self, context: ExecutionContext) -> None:
        """Notify all relevant observers."""
        observers = self.get_observers_for_state(context.state)

        for observer in observers:
            try:
                observer.update(context)
            except Exception as e:
                # Log error but don't propagate
                logging.error(f"Observer {observer.name} failed: {e}", exc_info=True)

    def get_observer_count(self) -> int:
        """Get total number of active observers."""
        with self._lock:
            return len(self._observers)


class ErrorIsolatingObserverManager(ConcurrentObserverManager):
    """Observer manager with enhanced error isolation."""

    def __init__(self, max_failures: int = 5):
        super().__init__()
        self._max_failures = max_failures
        self._failure_counts: Dict[Observer, int] = defaultdict(int)
        self._disabled_observers: Set[Observer] = set()

    def notify_observers(self, context: ExecutionContext) -> None:
        """Notify observers with circuit breaker pattern."""
        observers = self.get_observers_for_state(context.state)

        for observer in observers:
            if observer in self._disabled_observers:
                continue

            try:
                observer.update(context)
                # Reset failure count on success
                self._failure_counts[observer] = max(
                    0, self._failure_counts[observer] - 1
                )

            except Exception as e:
                self._handle_observer_error(observer, e, context)

    def _handle_observer_error(
        self, observer: Observer, error: Exception, context: ExecutionContext
    ) -> None:
        """Handle observer error with circuit breaker."""
        self._failure_counts[observer] += 1

        logging.error(
            f"Observer {observer.name} failed (failure #{self._failure_counts[observer]}): {error}",
            exc_info=True,
        )

        # Disable observer if too many failures
        if self._failure_counts[observer] >= self._max_failures:
            self._disabled_observers.add(observer)
            logging.warning(
                f"Observer {observer.name} disabled due to repeated failures"
            )

    def enable_observer(self, observer: Observer) -> None:
        """Re-enable a disabled observer."""
        with self._lock:
            self._disabled_observers.discard(observer)
            self._failure_counts[observer] = 0
