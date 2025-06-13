"""Base observer implementation."""

from abc import ABC, abstractmethod

from typing_compat import Any, Dict, Optional

from callpyback.core.context import ExecutionContext


class BaseObserver(ABC):
    """Abstract base class for observers."""

    def __init__(self, priority: int = 0, name: Optional[str] = None):
        self._priority = priority
        self._name = name or self.__class__.__name__
        self._metadata: Dict[str, Any] = {}

    @abstractmethod
    def update(self, context: ExecutionContext) -> None:
        """Handle execution context update."""
        pass

    @property
    def priority(self) -> int:
        """Observer execution priority."""
        return self._priority

    @property
    def name(self) -> str:
        """Observer name for identification."""
        return self._name

    @property
    def metadata(self) -> Dict[str, Any]:
        """Observer metadata."""
        return self._metadata.copy()

    def set_metadata(self, key: str, value: Any) -> None:
        """Set observer metadata."""
        self._metadata[key] = value
