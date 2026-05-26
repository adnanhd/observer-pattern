"""Demo handler module for the eventforge-network topology.

``python -m eventforge.worker --import handlers`` discovers the
``HANDLERS`` table below and serves each entry as an RPC method. Each
handler returns the serving container's hostname + pid so the demander
can show how calls fan out across the server pool.

Swap this file for your own: define plain functions and list them in
HANDLERS. Bind-mount the file into the container at /work (see
docker-compose.yml) -- no image rebuild needed when you edit it.
"""

from __future__ import annotations

import os
import socket
from typing import Any


def _whoami() -> dict[str, Any]:
    return {"host": socket.gethostname(), "pid": os.getpid()}


def compute(x: float) -> dict[str, Any]:
    """Toy CPU work: square the input, tagged with who served it."""
    return {**_whoami(), "input": x, "result": x * x}


def echo(payload: Any) -> dict[str, Any]:
    """Round-trip a payload, tagged with who served it."""
    return {**_whoami(), "echo": payload}


HANDLERS = {"compute": compute, "echo": echo}
SERVICE_NAME = "math"
