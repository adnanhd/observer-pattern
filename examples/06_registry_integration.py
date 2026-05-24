"""Example 06: eventforge transports + registry-pattern envelopes.

End-to-end story for the local-builds, remote-runs, result-returns split:

  - Local side: ``registry.serialize(instance)`` produces a JSON-safe
    envelope ``{type, data, meta}``.
  - Wire: ``RPCClient.call("train_step", envelope)`` ships the dict as a
    ``Message.payload`` over the in-memory ``MessageQueue`` (or TCP for
    the cross-process variant -- see example 07).
  - Remote side: the registered RPC method gets the envelope, calls
    ``registry.build(envelope)`` to reconstruct the instance, runs the
    work, returns a JSON-friendly result.
  - Local side gets the result back via the same RPC call.

eventforge never sees the model object itself -- only the JSON-shaped
envelope produced by registry-pattern. This is the "registry-pattern
owns serialization / message integrity, eventforge owns execution /
dispatch" division of responsibilities.

No real CPU work in this demo -- the point is the wire format. Run::

    PYTHONPATH=/path/to/registry-pattern:. python examples/06_registry_integration.py
"""

from __future__ import annotations

from typing import Any

from registry import TypeRegistry, build, serialize

from eventforge import MessageQueue, RPCClient, RPCServer

# =============================================================================
# Domain: a tiny model registered with registry-pattern
# =============================================================================


class ModelRegistry(TypeRegistry[Any], repo="examples.models"):
    pass


@ModelRegistry.register_artifact
class MLP:
    """Plain-Python stand-in for a real torch model."""

    def __init__(
        self, in_features: int = 4, hidden: int = 8, out_features: int = 2
    ) -> None:
        self.in_features = in_features
        self.hidden = hidden
        self.out_features = out_features

    def predict(self, x: list[float]) -> list[float]:
        # Trivial "forward" so the example has SOME computation.
        return [sum(x) % (self.out_features or 1)] * self.out_features


# =============================================================================
# Remote side: RPCServer registers a handler that uses registry.build
# =============================================================================


def remote_train_step(envelope: dict[str, Any], batch: list[float]) -> dict[str, Any]:
    """Handler running on the "remote" side.

    Receives a registry-pattern envelope + payload, reconstructs the model
    with ``build()``, performs work, returns a JSON-friendly dict.
    """
    model = build(envelope)
    prediction = model.predict(batch)
    return {
        "prediction": prediction,
        "model_class": type(model).__name__,
        "n_features": model.in_features,
    }


# =============================================================================
# Driver
# =============================================================================


def main() -> None:
    queue = MessageQueue()

    # Start the RPC server in a background thread (single in-memory queue).
    server = RPCServer(queue, service_name="learner")
    server.add_method("train_step", remote_train_step)
    server.serve(blocking=False)

    try:
        client = RPCClient(queue, service_name="learner")

        # 1) Build a model LOCALLY and serialize it through registry-pattern.
        local_model = MLP(in_features=4, hidden=16, out_features=2)
        envelope = serialize(local_model, serializator="python", repo="examples.models")
        print("envelope on the wire:", envelope)

        # 2) Dispatch the envelope + a batch to the remote handler via eventforge.
        result = client.call("train_step", envelope, [1.0, 2.0, 3.0, 4.0])
        print("\nremote result:", result)

        # 3) Reconstructed model on the remote side matches the local definition.
        assert result["model_class"] == "MLP"
        assert result["n_features"] == 4
        print("\nround-trip OK -- registry-pattern serialized, eventforge dispatched.")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
