from enum import Enum
from typing import Callable, Dict, Any, Set
from typing_extensions import Optional

from .reduction import Reduction
from .scheduling import Policy, SinglePolicy
from .callbacklist import CallbackList


class EventDispatcher:
    def __init__(
        self,
        policy: Policy = SinglePolicy(),
        reduction: Optional[Reduction] = None,
        allowed_parameters: Set[str] = set(),
    ):
        """Initializes the EventDispatcher with a specified threading policy and allowed parameters.

        Args:
            policy (Policy): The policy that dictates how listeners are executed.
            allowed_parameters (Set[str]): A set of allowed parameters that listeners can accept.
        """
        self.policy = policy
        self.reduction = reduction
        self.allowed_parameters = allowed_parameters
        self.listeners: Dict[Enum, CallbackList] = {}

    def append_listener(self, event_type: Enum, listener: Callable) -> None:
        """Adds a listener to the specified event type.

        Args:
            event_type (Enum): The type of event to listen for.
            listener (Callable): The listener function to be executed when the event is dispatched.
        """
        if event_type not in self.listeners:
            self.listeners[event_type] = CallbackList(
                policy=self.policy,
                reduction=self.reduction,
                allowed_parameters=self.allowed_parameters,
            )
        self.listeners[event_type].add_callback(listener)

    def remove_listener(self, event_type: Enum, listener: Callable) -> None:
        """Removes a listener from the specified event type.

        Args:
            event_type (Enum): The type of event to remove the listener from.
            listener (Callable): The listener function to be removed.
        """
        if event_type in self.listeners:
            self.listeners[event_type].remove_callback(listener)

    def dispatch(self, event_type: Enum, **kwargs: Any) -> None:
        """Dispatches an event of the given type, executing all associated listeners.

        The first argument is always the event type, followed by any arguments
        to be passed to the listener functions.

        Args:
            event_type (Enum): The type of event to dispatch.
            *args: Positional arguments to pass to the listeners.
            **kwargs: Keyword arguments to pass to the listeners.
        """
        if event_type in self.listeners:
            self.listeners[event_type].run_callbacks(**kwargs)
            self.listeners[event_type].join_callbacks()
