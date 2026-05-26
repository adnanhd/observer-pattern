"""Caller protocol unifying local execution and RPC dispatch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Caller(Protocol):
    """Structural protocol for anything that can execute a target.

    Both :class:`~eventforge.executor.LocalProcedureCaller` (runs the
    callable in-process) and :class:`~eventforge.rpc.RPCClient` (dispatches
    to a remote method by name) satisfy this, so ``@task`` can target
    either transparently.
    """

    def call(
        self, target: Callable[..., Any] | str, *args: Any, **kwargs: Any
    ) -> Any: ...
