"""Remote Procedure Call over message queue."""

import asyncio
import functools
import threading
import time
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from callpyback.executor import ExecutionMode, Executor
from callpyback.queue import MessageQueue
from callpyback.types import Message, RPCRequest, RPCResponse


class RPCServer:
    """RPC server that handles method calls via message queue."""

    def __init__(
        self,
        queue: MessageQueue,
        executor: Optional[Executor] = None,
        service_name: str = "rpc",
    ):
        self._queue = queue
        self._executor = executor or Executor()
        self._service_name = service_name
        self._methods: Dict[str, Callable] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def register(self, name: Optional[str] = None) -> Callable:
        """Decorator to register RPC method."""

        def decorator(func: Callable) -> Callable:
            method_name = name or func.__name__
            self._methods[method_name] = func
            return func

        return decorator

    def add_method(self, name: str, func: Callable) -> None:
        """Register method directly."""
        self._methods[name] = func

    def serve(self, blocking: bool = True) -> None:
        """Start serving RPC requests."""
        if self._running:
            return

        self._running = True
        topic = f"{self._service_name}.request"

        def handler(msg: Message):
            self._handle_request(msg)

        self._queue.subscribe(topic, handler)

        if blocking:
            self._serve_loop()
        else:
            self._thread = threading.Thread(target=self._serve_loop, daemon=True)
            self._thread.start()

    async def serve_async(self) -> None:
        """Serve requests asynchronously."""
        self._running = True
        topic = f"{self._service_name}.request"

        while self._running:
            msg = await self._queue.receive_async(topic, timeout=1.0)
            if msg:
                await self._handle_request_async(msg)

    def stop(self) -> None:
        """Stop serving."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _serve_loop(self) -> None:
        """Main serving loop."""
        topic = f"{self._service_name}.request"
        while self._running:
            msg = self._queue.receive(topic, timeout=1.0)
            if msg:
                self._handle_request(msg)

    def _handle_request(self, msg: Message) -> None:
        """Handle incoming RPC request."""
        try:
            request = RPCRequest.model_validate(msg.payload)
        except Exception as e:
            if msg.reply_to:
                response = RPCResponse(
                    id=str(uuid4()),
                    request_id=msg.payload.get("id", "unknown")
                    if isinstance(msg.payload, dict)
                    else "unknown",
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

    def __exit__(self, *args) -> None:
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
        self, method: str, *args, timeout: Optional[float] = None, **kwargs
    ) -> Any:
        """Call remote method synchronously."""
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
        self, method: str, *args, timeout: Optional[float] = None, **kwargs
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

    def __getattr__(self, name: str) -> Callable:
        """Allow client.method_name(*args) syntax."""

        def caller(*args, **kwargs):
            return self.call(name, *args, **kwargs)

        return caller
