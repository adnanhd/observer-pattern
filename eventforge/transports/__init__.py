"""Message transports for eventforge.

Two optional transports are NOT imported here because they pull in optional
third-party dependencies. Import them explicitly when needed:

    from eventforge.transports.redis import RedisTransport  # eventforge[redis]
    from eventforge.transports.nats import NatsTransport  # eventforge[nats]
"""

from __future__ import annotations

from eventforge.transports.base import Transport, TransportFullError
from eventforge.transports.memory import MemoryTransport
from eventforge.transports.tcp import TCPClientTransport, TCPServerTransport

__all__ = [
    "Transport",
    "TransportFullError",
    "MemoryTransport",
    "TCPServerTransport",
    "TCPClientTransport",
]
