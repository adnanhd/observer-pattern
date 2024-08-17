from typing import Callable, Dict, Any, Set, Type, Optional

from .reduction import Reduction
from .scheduling import Policy, ThreadingPolicy, SinglePolicy
from .callbacklist import CallbackList


class CallbackHandler:
    def __init__(
        self, policy: Policy = ThreadingPolicy(), reduction: Optional[Reduction] = None
    ):
        """Initializes the Handler with a specified threading policy."""
        self.policy = policy
        self.reduction = reduction
        self.delegations: Dict[str, CallbackList] = {}

    def add_delegation(self, action: str, allowed_parameters: Set[str]) -> None:
        """Adds a delegation for an action with specified allowed parameters."""
        self.delegations[action] = CallbackList(
            reduction=self.reduction,
            policy=self.policy,
            allowed_parameters=allowed_parameters,
        )

    def delegate_function(self, **kwargs: Callable) -> None:
        """Delegates a function to the appropriate action."""
        for action, func in kwargs.items():
            if action in self.delegations:
                self.delegations[action].add_callback(func)
            else:
                raise ValueError(f"No delegation exists for action '{action}'")

    def delegate_class(self, instance: Any) -> None:
        """Delegates methods of a class instance that are marked with @delegatedmethod."""
        for name in dir(instance):
            if name in self.delegations:
                method = getattr(instance, name)
                if callable(method) and getattr(method, "_is_delegated", False):
                    self.delegations[name].add_callback(method)

    def execute(self, action: str, **kwargs: Any) -> None:
        """Executes the delegated function(s) for a given action."""
        if action in self.delegations:
            self.delegations[action].run_callbacks(**kwargs)
            self.delegations[action].join_callbacks()
        else:
            raise ValueError(f"No delegation exists for action '{action}'")


def delegatedmethod(func):
    """Decorator to mark a method as delegatable."""
    func._is_delegated = True
    return func
