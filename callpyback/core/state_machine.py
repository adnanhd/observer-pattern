"""State machine implementation for execution flow."""

import threading
from enum import Enum, auto

from typing_compat import Dict, List, Set

from callpyback.errors import StateTransitionError


class ExecutionState(Enum):
    """States in the execution lifecycle."""

    INITIALIZED = auto()
    PRE_EXECUTION = auto()
    EXECUTING = auto()
    POST_SUCCESS = auto()
    POST_FAILURE = auto()
    COMPLETED = auto()
    ERROR = auto()


class ExecutionPhase(Enum):
    """Execution phases for observer registration."""

    BEFORE_CALL = auto()
    AFTER_SUCCESS = auto()
    AFTER_FAILURE = auto()
    AFTER_COMPLETION = auto()
    ON_ERROR = auto()


class StateMachine:
    """Thread-safe state machine for execution flow."""

    # Valid state transitions
    TRANSITIONS: Dict[ExecutionState, Set[ExecutionState]] = {
        ExecutionState.INITIALIZED: {ExecutionState.PRE_EXECUTION},
        ExecutionState.PRE_EXECUTION: {ExecutionState.EXECUTING, ExecutionState.ERROR},
        ExecutionState.EXECUTING: {
            ExecutionState.POST_SUCCESS,
            ExecutionState.POST_FAILURE,
            ExecutionState.ERROR,
        },
        ExecutionState.POST_SUCCESS: {ExecutionState.COMPLETED},
        ExecutionState.POST_FAILURE: {ExecutionState.COMPLETED},
        ExecutionState.COMPLETED: set(),  # Terminal
        ExecutionState.ERROR: set(),  # Terminal
    }

    def __init__(self, initial_state: ExecutionState = ExecutionState.INITIALIZED):
        self._current_state = initial_state
        self._state_history: List[ExecutionState] = [initial_state]
        self._lock = threading.RLock()

    def transition_to(self, new_state: ExecutionState) -> None:
        """Transition to new state with validation."""
        with self._lock:
            valid_transitions = self.TRANSITIONS.get(self._current_state, set())

            if new_state not in valid_transitions:
                raise StateTransitionError(
                    from_state=self._current_state.name,
                    to_state=new_state.name,
                    valid_transitions=[s.name for s in valid_transitions],
                )

            self._current_state = new_state
            self._state_history.append(new_state)

    @property
    def current_state(self) -> ExecutionState:
        """Get current state."""
        with self._lock:
            return self._current_state

    @property
    def state_history(self) -> List[ExecutionState]:
        """Get state transition history."""
        with self._lock:
            return self._state_history.copy()

    def can_transition_to(self, state: ExecutionState) -> bool:
        """Check if transition is valid."""
        with self._lock:
            valid_transitions = self.TRANSITIONS.get(self._current_state, set())
            return state in valid_transitions

    def is_terminal(self) -> bool:
        """Check if current state is terminal."""
        with self._lock:
            return len(self.TRANSITIONS.get(self._current_state, set())) == 0
