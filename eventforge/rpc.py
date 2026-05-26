"""Remote Procedure Call over message queue."""

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from eventforge.executor import Executor
from eventforge.queue import MessageQueue
from eventforge.types import Message, RPCRequest, RPCResponse


class RPCServer:
    """RPC server: handles method calls as Eventful subscribers on the
    request topic instead of polling.

    Each :meth:`add_method` call attaches a handler to the request
    topic's underlying :class:`Eventful`, so incoming RPC requests are
    dispatched via the queue's pub-sub machinery (transport -> topic
    Eventful -> handler) with no dedicated serve loop. ``serve(blocking=True)``
    just blocks the calling thread on a stop-event instead of polling.
    """

    def __init__(
        self,
        queue: MessageQueue,
        executor: Executor | None = None,
        service_name: str = "rpc",
    ):
        self._queue = queue
        self._executor = executor or Executor()
        self._service_name = service_name
        self._methods: dict[str, Callable[..., Any]] = {}
        self._running = False
        self._sub_id: str | None = None
        self._stop_event = threading.Event()

    def register(
        self, name: str | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator to register RPC method."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            method_name = name or func.__name__
            self._methods[method_name] = func
            return func

        return decorator

    def add_method(self, name: str, func: Callable[..., Any]) -> None:
        """Register method directly."""
        self._methods[name] = func

    def serve(self, blocking: bool = True) -> None:
        """Subscribe the dispatch handler to the request topic. When
        ``blocking=True``, block the calling thread until :meth:`stop`
        is called (or the process is killed); otherwise return
        immediately and let the transport's delivery thread invoke the
        handler in the background."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        topic = f"{self._service_name}.request"
        self._sub_id = self._queue.on(topic, self._handle_request)
        if blocking:
            try:
                while not self._stop_event.is_set():
                    self._stop_event.wait(timeout=1.0)
            except KeyboardInterrupt:
                pass

    async def serve_async(self) -> None:
        """Async variant: subscribe + await stop event."""
        self._running = True
        self._stop_event.clear()
        topic = f"{self._service_name}.request"
        self._sub_id = self._queue.on(topic, self._handle_request)
        while not self._stop_event.is_set():
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        """Unsubscribe + release the blocked serve thread."""
        self._running = False
        self._stop_event.set()
        if self._sub_id is not None:
            self._queue.unsubscribe(self._sub_id)
            self._sub_id = None

    def _handle_request(self, msg: Message) -> None:
        """Handle incoming RPC request."""
        try:
            request = RPCRequest.model_validate(msg.payload)
        except Exception as e:
            if msg.reply_to:
                response = RPCResponse(
                    id=str(uuid4()),
                    request_id=(
                        msg.payload.get("id", "unknown")
                        if isinstance(msg.payload, dict)
                        else "unknown"
                    ),
                    error=f"Invalid request: {e}",
                    error_type="ValidationError",
                )
                self._queue.publish(msg.reply_to, response.model_dump())
            return

        method = self._methods.get(request.method)
        if not method:
            if msg.reply_to:
                response = RPCResponse(
                    id=str(uuid4()),
                    request_id=request.id,
                    error=f"Method not found: {request.method}",
                    error_type="MethodNotFound",
                )
                self._queue.publish(msg.reply_to, response.model_dump())
            return

        try:
            result = method(*request.args, **request.kwargs)
            response = RPCResponse(
                id=str(uuid4()), request_id=request.id, result=result
            )
        except Exception as e:
            response = RPCResponse(
                id=str(uuid4()),
                request_id=request.id,
                error=str(e),
                error_type=type(e).__name__,
            )

        if msg.reply_to:
            self._queue.publish(msg.reply_to, response.model_dump())

    async def _handle_request_async(self, msg: Message) -> None:
        """Handle request asynchronously."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._handle_request(msg))

    def __enter__(self) -> "RPCServer":
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()


class RPCClient:
    """RPC client for calling remote methods."""

    def __init__(
        self,
        queue: MessageQueue,
        service_name: str = "rpc",
        timeout: float = 30.0,
    ):
        self._queue = queue
        self._service_name = service_name
        self._timeout = timeout

    def call(
        self,
        method: str,
        *args: Any,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Call a remote method by name synchronously."""
        request = RPCRequest(
            method=method, args=args, kwargs=kwargs, timeout=timeout or self._timeout
        )

        reply_topic = f"_rpc_reply.{request.id}"
        topic = f"{self._service_name}.request"

        msg = Message(
            topic=topic,
            payload=request.model_dump(),
            reply_to=reply_topic,
            correlation_id=request.id,
        )

        self._queue._transport.send(msg)

        response_msg = self._queue.receive(
            reply_topic, timeout=timeout or self._timeout
        )
        if not response_msg:
            raise TimeoutError(f"RPC call to {method} timed out")

        response = RPCResponse.model_validate(response_msg.payload)
        if response.error:
            raise Exception(f"{response.error_type}: {response.error}")

        return response.result

    async def call_async(
        self, method: str, *args: Any, timeout: float | None = None, **kwargs: Any
    ) -> Any:
        """Call remote method asynchronously."""
        request = RPCRequest(
            method=method, args=args, kwargs=kwargs, timeout=timeout or self._timeout
        )

        reply_topic = f"_rpc_reply.{request.id}"
        topic = f"{self._service_name}.request"

        msg = Message(
            topic=topic,
            payload=request.model_dump(),
            reply_to=reply_topic,
            correlation_id=request.id,
        )

        self._queue._transport.send(msg)

        response_msg = await self._queue.receive_async(
            reply_topic, timeout=timeout or self._timeout
        )
        if not response_msg:
            raise TimeoutError(f"RPC call to {method} timed out")

        response = RPCResponse.model_validate(response_msg.payload)
        if response.error:
            raise Exception(f"{response.error_type}: {response.error}")

        return response.result

    def __getattr__(self, name: str) -> Callable[..., Any]:
        """Allow client.method_name(*args) syntax."""

        def caller(*args: Any, **kwargs: Any) -> Any:
            return self.call(name, *args, **kwargs)

        return caller


class RoundRobinRPCClient:
    """Dispatch RPC calls round-robin across a pool of ``RPCClient`` instances.

    Each underlying client typically connects to a different worker process
    (or remote host). Useful when you have N workers serving the same set
    of RPC methods and want trivial load balance without an external proxy.

    Example::

        clients = [
            RPCClient(MessageQueue(transport=TCPClientTransport("worker1", 9090))),
            RPCClient(MessageQueue(transport=TCPClientTransport("worker2", 9090))),
        ]
        lb = RoundRobinRPCClient(clients)
        result = lb.call("train_step", envelope)
    """

    def __init__(self, clients: list["RPCClient"]):
        if not clients:
            raise ValueError("RoundRobinRPCClient requires at least one RPCClient")
        self._clients: list[RPCClient] = list(clients)
        self._idx = 0
        self._lock = threading.Lock()

    def _next_client(self) -> "RPCClient":
        with self._lock:
            client = self._clients[self._idx]
            self._idx = (self._idx + 1) % len(self._clients)
        return client

    def call(
        self,
        method: str,
        *args: Any,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._next_client().call(method, *args, timeout=timeout, **kwargs)

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def caller(*args: Any, **kwargs: Any) -> Any:
            return self.call(name, *args, **kwargs)

        return caller


def with_retry(
    client: "RPCClient",
    *,
    max_retries: int = 3,
    backoff_initial: float = 0.1,
    backoff_factor: float = 2.0,
    retry_on: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError),
) -> "RPCClient":
    """Wrap ``client`` so each ``call()`` retries up to ``max_retries`` times.

    Exponential backoff: ``backoff_initial`` seconds before retry 1,
    multiplied by ``backoff_factor`` each subsequent attempt.

    Only the exception types in ``retry_on`` trigger a retry; everything
    else propagates immediately so application errors aren't masked.
    """

    class _RetryingClient(RPCClient):
        def __init__(self) -> None:
            self._client = client
            self._max_retries = max_retries
            self._backoff_initial = backoff_initial
            self._backoff_factor = backoff_factor
            self._retry_on = retry_on

        def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
            delay = self._backoff_initial
            last_exc: BaseException | None = None
            for attempt in range(self._max_retries + 1):
                try:
                    return self._client.call(method, *args, **kwargs)
                except self._retry_on as exc:
                    last_exc = exc
                    if attempt == self._max_retries:
                        raise
                    time.sleep(delay)
                    delay *= self._backoff_factor
            # Unreachable, but keeps mypy happy
            assert last_exc is not None
            raise last_exc  # pragma: no cover

        def __getattr__(self, name: str) -> Callable[..., Any]:
            def caller(*args: Any, **kwargs: Any) -> Any:
                return self.call(name, *args, **kwargs)

            return caller

    return _RetryingClient()
