"""Shared domain + RPC handler for example 07's distributed worker pool.

Single source of truth for the fleet: the registry, the model, and the
``train_step`` handler live here once -- no stringified copy. The module
also satisfies the ``eventforge.worker`` entrypoint contract
(``HANDLERS`` + ``SERVICE_NAME``), so a worker is just::

    python -m eventforge.worker --import distributed_handlers \
        --service learner --port 19090

which is exactly how ``07_distributed_workers.py`` spawns its workers and
exactly the shape ``deploy/topology/handlers.py`` bind-mounts into a
container. Same contract, example -> container. The bind/serve internals
the entrypoint performs live in ``eventforge/worker.py``.
"""

from __future__ import annotations

import os
from typing import Any

from registry import TypeRegistry, build


class ModelRegistry(TypeRegistry[Any], repo="examples.distributed.models"):
    pass


@ModelRegistry.register_artifact
class MLP:
    def __init__(
        self, in_features: int = 4, hidden: int = 8, out_features: int = 2
    ) -> None:
        self.in_features = in_features
        self.hidden = hidden
        self.out_features = out_features

    def predict(self, x: list[float]) -> list[float]:
        return [sum(x) % (self.out_features or 1)] * self.out_features


def train_step(envelope: dict, batch: list[float]) -> dict[str, Any]:
    """Reconstruct the model from its envelope and run a forward pass."""
    model = build(envelope)
    return {
        "worker_pid": os.getpid(),
        "model_class": type(model).__name__,
        "prediction": model.predict(batch),
    }


# eventforge.worker entrypoint contract
HANDLERS = {"train_step": train_step}
SERVICE_NAME = "learner"
