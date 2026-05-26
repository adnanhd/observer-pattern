"""Caller protocol for local task execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Caller(Protocol):
    """Structural protocol for a local execution backend.

    A ``Caller`` runs a callable and returns its value;
    :class:`~eventforge.executor.LocalProcedureCaller` satisfies it
    (inline / thread / process). ``@task(caller=...)`` uses it to decide
    HOW the task body runs in-process.

    Remote execution is a separate concern: register the task function on
    an :class:`~eventforge.rpc.RPCServer` and call it by name with
    :class:`~eventforge.rpc.RPCClient` -- not via this protocol.
    """

    def call(self, target: Callable[..., Any], *args: Any, **kwargs: Any) -> Any: ...
