"""Logfire integration — sends task lifecycle and metric spans to Pydantic Logfire.

Requires: ``pip install logfire``

The LogfireObserver creates OpenTelemetry spans for each task execution,
recording timing, arguments, results, errors, and custom attributes
extracted from the execution context.

Usage with @task::

    from callpyback import task
    from callpyback.integrations.logfire import LogfireObserver

    import logfire
    logfire.configure()

    logfire_obs = LogfireObserver()

    @task(on_execute=[logfire_obs])
    def train_epoch(epoch):
        return {"loss": 0.5, "accuracy": 0.9}

Usage with @observe::

    from callpyback.observers import observe
    from callpyback.integrations.logfire import LogfireObserver

    logfire_obs = LogfireObserver(
        extract_attributes=lambda ctx: ctx.result or {},
        span_name=lambda ctx: f"train.{ctx.func_name}",
    )

    @observe(logfire_obs)
    def train_batch(batch):
        return {"loss": 0.42}
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional, Union

try:
    import logfire as _logfire
except ImportError:
    raise ImportError(
        "logfire is required for LogfireObserver. "
        "Install it with: pip install logfire"
    )

from callpyback.observers import ExecutionContext, Observer


class LogfireObserver(Observer):
    """Observer that sends execution spans to Pydantic Logfire.

    Each task execution creates a Logfire span with:
    - Function name and arguments (optional)
    - Execution duration (automatic via span timing)
    - Result attributes (extracted via ``extract_attributes``)
    - Error information on failure

    Args:
        logfire_instance: A ``logfire.Logfire`` instance. If None, uses the
            default (module-level) logfire instance.
        span_name: Either a static string or a callable that takes an
            ExecutionContext and returns the span name.
            Default: ``ctx.func_name``.
        extract_attributes: A callable that takes an ExecutionContext and
            returns a dict of extra attributes to attach to the span.
            Called on_success when ctx.result is available. Default: None.
        log_args: Whether to record function arguments as span attributes.
            Default: False.
        log_result: Whether to record the raw result as a span attribute.
            Default: False.
        tags: Static tags to attach to every span.
    """

    def __init__(
        self,
        logfire_instance: Optional[Any] = None,
        span_name: Union[str, Callable[[ExecutionContext], str], None] = None,
        extract_attributes: Optional[
            Callable[[ExecutionContext], Dict[str, Any]]
        ] = None,
        log_args: bool = False,
        log_result: bool = False,
        tags: Optional[List[str]] = None,
    ):
        self._logfire = logfire_instance or _logfire
        self._span_name = span_name
        self._extract_attributes = extract_attributes
        self._log_args = log_args
        self._log_result = log_result
        self._tags = tags or []

        # Store active spans keyed by id(ctx)
        self._active_spans: Dict[int, Any] = {}
        self._lock = threading.Lock()

    def _get_span_name(self, ctx: ExecutionContext) -> str:
        if self._span_name is None:
            return ctx.func_name
        if callable(self._span_name):
            return self._span_name(ctx)
        return self._span_name

    def on_start(self, ctx: ExecutionContext) -> None:
        """Open a Logfire span for this execution."""
        name = self._get_span_name(ctx)

        # Build initial attributes
        attributes: Dict[str, Any] = {}
        if self._log_args:
            attributes["args"] = repr(ctx.args) if ctx.args else None
            attributes["kwargs"] = repr(ctx.kwargs) if ctx.kwargs else None

        # Use logfire.span() as a context manager — we enter it here
        # and exit it in on_success/on_failure
        if self._tags:
            lf = self._logfire.with_tags(*self._tags)
        else:
            lf = self._logfire

        span = lf.span(name, **attributes)
        span.__enter__()

        ctx_id = id(ctx)
        with self._lock:
            self._active_spans[ctx_id] = span

    def on_success(self, ctx: ExecutionContext) -> None:
        """Close the span, attaching result attributes."""
        ctx_id = id(ctx)
        with self._lock:
            span = self._active_spans.pop(ctx_id, None)

        if span is None:
            return

        try:
            # Set extracted attributes on the span
            if self._extract_attributes and ctx.is_success:
                try:
                    attrs = self._extract_attributes(ctx)
                    if attrs:
                        span.set_attribute("result_attributes", attrs)
                except Exception:
                    pass

            if self._log_result and ctx.result is not None:
                span.set_attribute("result", repr(ctx.result))

            if not ctx.is_success and ctx.error is not None:
                span.set_attribute("error", str(ctx.error))
                span.set_attribute("error_type", type(ctx.error).__name__)

            span.set_attribute("execution_time", ctx.execution_time)
        finally:
            # Exit the span (success or failure)
            if ctx.error is not None:
                span.__exit__(type(ctx.error), ctx.error, ctx.error.__traceback__)
            else:
                span.__exit__(None, None, None)

    def on_failure(self, ctx: ExecutionContext) -> None:
        """Close the span with error information."""
        self.on_success(ctx)


class LogfireMetricLogger:
    """Standalone helper to log metric dicts to Logfire as info messages.

    Useful inside training loops where you don't need full span lifecycle
    but want to push per-epoch or per-batch metrics to Logfire.

    Usage::

        metric_logger = LogfireMetricLogger(prefix="train")

        for epoch in range(100):
            loss = train_one_epoch()
            metric_logger.log(epoch=epoch, loss=loss, accuracy=acc)

    This emits a Logfire info message with all kwargs as structured attributes.
    """

    def __init__(
        self,
        logfire_instance: Optional[Any] = None,
        prefix: str = "metrics",
        tags: Optional[List[str]] = None,
    ):
        self._logfire = logfire_instance or _logfire
        self._prefix = prefix
        if tags:
            self._logfire = self._logfire.with_tags(*tags)

    def log(self, **kwargs: Any) -> None:
        """Log metrics as a Logfire info message."""
        msg = f"{self._prefix}: " + " ".join(
            f"{k}={v}" for k, v in kwargs.items()
        )
        self._logfire.info(msg, **kwargs)
