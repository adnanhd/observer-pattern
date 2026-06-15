"""Abstract transport interface."""
from __future__ import annotations
from typing import Optional

from abc import ABC, abstractmethod
from collections.abc import Callable

from eventforge.types import Message


class Transport(ABC):
    """Abstract base for message transports."""

    @abstractmethod
    def send(self, message: Message) -> None:
        """Send message to its topic."""
        pass

    @abstractmethod
    def receive(self, topic: str, timeout: Optional[float] = None) -> Optional[Message]:
        """Receive next message from topic (blocking)."""
        pass

    @abstractmethod
    async def receive_async(
        self, topic: str, timeout: Optional[float] = None
    ) -> Optional[Message]:
        """Receive next message from topic (async)."""
        pass

    @abstractmethod
    def subscribe(self, topic: str, callback: Callable[[Message], None]) -> str:
        """Subscribe to topic. Returns subscription_id."""
        pass

    @abstractmethod
    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe. Returns True if found."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close transport and release resources."""
        pass
