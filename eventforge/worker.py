"""Generic RPC server worker -- ``python -m eventforge.worker``.

Turns any module that exposes a ``HANDLERS`` table into a long-running
RPC server bound to a TCP port, with no transport boilerplate. This is
the containerizable counterpart to the inlined worker source in
``examples/07_distributed_workers.py``: instead of a process spawning a
worker from a string blob, you point the entrypoint at a module.

A *server* in an eventforge-network topology runs this; a *demander*
(client) connects with ``RPCClient`` / ``RoundRobinRPCClient`` over the
same ``service_name`` and round-robins calls across the server pool.
See ``deploy/`` for the docker-compose topology.

Contract for the imported module:

    # handlers.py
    def train_step(envelope, batch):
        ...
        return {...}

    HANDLERS = {"train_step": train_step}   # required: name -> callable
    SERVICE_NAME = "learner"                 # optional: default "rpc"

Run::

    python -m eventforge.worker --import handlers --port 9090
    python -m eventforge.worker --import handlers --service learner \
        --host 0.0.0.0 --port 9090

The transport is a length-prefixed JSON TCP socket with no auth/TLS --
bind it on a trusted network (docker/k8s internal, HPC interconnect),
never a public interface.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import signal
from collections.abc import Callable

from eventforge import MessageQueue, RPCServer
from eventforge.transports.tcp import TCPServerTransport

logger = logging.getLogger("eventforge.worker")


def _load_handlers(
    module_path: str,
) -> tuple[dict[str, Callable[..., object]], str | None]:
    """Import ``module_path`` and return its ``(HANDLERS, SERVICE_NAME)``.

    Raises SystemExit with a clear message on the common failure modes
    (module not importable, missing/empty/ill-typed HANDLERS).
    """
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise SystemExit(
            f"eventforge.worker: cannot import handler module {module_path!r}: {exc}\n"
            f"  (is it on PYTHONPATH? inside a container, bind-mount or COPY it in)"
        ) from exc

    handlers = getattr(module, "HANDLERS", None)
    if not isinstance(handlers, dict) or not handlers:
        raise SystemExit(
            f"eventforge.worker: module {module_path!r} must define a non-empty "
            f"HANDLERS dict of {{name: callable}}; found {type(handlers).__name__}."
        )
    bad = [k for k, v in handlers.items() if not callable(v)]
    if bad:
        raise SystemExit(f"eventforge.worker: HANDLERS entries are not callable: {bad}")

    service_name = getattr(module, "SERVICE_NAME", None)
    return handlers, service_name


def serve(
    module_path: str,
    host: str = "0.0.0.0",
    port: int = 9090,
    service_name: str | None = None,
) -> None:
    """Bind a TCP RPC server exposing ``module_path``'s HANDLERS and block."""
    handlers, module_service = _load_handlers(module_path)
    service = service_name or module_service or "rpc"

    transport = TCPServerTransport(host=host, port=port)
    transport.start()
    queue = MessageQueue(transport=transport)
    server = RPCServer(queue, service_name=service)
    for name, func in handlers.items():
        server.add_method(name, func)

    # docker stop / kubectl delete send SIGTERM; serve() only unblocks on
    # its stop-event (or SIGINT). Bridge SIGTERM -> server.stop() so the
    # container exits cleanly instead of being SIGKILL'd after the grace period.
    def _shutdown(signum: int, _frame: object) -> None:
        logger.info("worker: received signal %s, stopping", signum)
        server.stop()

    signal.signal(signal.SIGTERM, _shutdown)

    logger.info(
        "worker: service=%r methods=%s listening on %s:%d",
        service,
        sorted(handlers),
        host,
        port,
    )
    try:
        server.serve(blocking=True)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        transport.close()
        logger.info("worker: stopped")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m eventforge.worker",
        description="Run a module's HANDLERS as an RPC server over TCP.",
    )
    parser.add_argument(
        "--import",
        dest="module",
        required=True,
        metavar="MODULE",
        help="Importable module exposing a HANDLERS dict (e.g. mypkg.handlers)",
    )
    parser.add_argument(
        "--service",
        default=None,
        help="RPC service name (default: module's SERVICE_NAME, else 'rpc')",
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Bind address (default 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=9090, help="TCP port (default 9090)"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (default INFO)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    serve(args.module, host=args.host, port=args.port, service_name=args.service)


if __name__ == "__main__":
    main()
