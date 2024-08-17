from typing import Callable, Dict, List, Tuple, Any, Set, Optional
from .scheduling import Policy, SinglePolicy
from .callbacklist import CallbackList
from .reduction import Reduction
from enum import Enum


class EventQueue:
    def __init__(
        self,
        policy: Policy = SinglePolicy(),
        reduction: Optional[Reduction] = None,
        allowed_parameters: Set[str] = set(),
    ):
        """Initializes the EventQueue with a specified threading policy and allowed parameters.

        Args:
            policy (Policy): The policy that dictates how listeners are executed.
            allowed_parameters (Set[str]): A set of allowed parameters that listeners can accept.
        """
        self.policy = policy
        self.reduction = reduction
        self.allowed_parameters = allowed_parameters
        self.listeners: Dict[Enum, CallbackList] = {}
        self.queue: List[Tuple[Enum, Dict[str, Any]]] = []

    def append_listener(self, event_type: Enum, listener: Callable) -> None:
        """Adds a listener to the specified event type.

        Args:
            event_type (Enum): The type of event to listen for.
            listener (Callable): The listener function to be executed when the event is dispatched.
        """
        if event_type not in self.listeners:
            self.listeners[event_type] = CallbackList(
                reduction=self.reduction,
                policy=self.policy,
                allowed_parameters=self.allowed_parameters,
            )
        self.listeners[event_type].add_callback(listener)

    def enqueue(self, event_type: Enum, **kwargs: Any) -> None:
        """Enqueues an event with its arguments. Listeners are not triggered during enqueue.

        Args:
            event_type (Enum): The type of event to enqueue.
            *args: Positional arguments to store for the event.
            **kwargs: Keyword arguments to store for the event.
        """
        self.queue.append((event_type, kwargs))

    def process(self) -> None:
        """Processes the event queue, dispatching all queued events to the appropriate listeners."""
        waiting = []
        while self.queue:
            event_type, kwargs = self.queue.pop(0)
            if event_type in self.listeners:
                self.listeners[event_type].run_callbacks(**kwargs)
                waiting.append(event_type)

        while waiting:
            event_type = waiting.pop(0)
            self.listeners[event_type].join_callbacks()
