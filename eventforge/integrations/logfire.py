"""Logfire integration -- send task lifecycle + metrics to Pydantic Logfire.

Requires: ``pip install logfire``  (or ``pip install eventforge[logfire]``)

:class:`LogfireMeter` opens an OpenTelemetry span per task execution,
recording timing, optional args / result, errors, and any attributes
your callback extracts. :class:`LogfireMetricLogger` is a standalone
helper for per-epoch / per-batch metric dicts that don't need a full
span lifecycle.

Usage with the ``@task`` decorator::

    import logfire
    from eventforge import task
    from eventforge.integrations.logfire import LogfireMeter

    logfire.configure()
    logfire_meter = LogfireMeter()

    @task
    def train_epoch(epoch):
        return {"loss": 0.5}

    runner = train_epoch.runner()
    logfire_meter.attach(runner)
    runner.run(epoch=1)

Or with the ``@observe`` decorator -- since :class:`LogfireMeter` is
itself a :class:`~eventforge.Meter`, you wire it the same way as the
other built-in meters (TimingMeter, MemoryMeter, ...).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

try:
    import logfire as _logfire  # type: ignore[import-not-found]
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "logfire is required for LogfireMeter. "
        "Install it with: pip install eventforge[logfire]"
    ) from e

from eventforge.observers import Context, Meter


class LogfireMeter(Meter):
    """Meter that opens / closes a Logfire span per task execution.

    Each lifecycle call attaches more attributes to the active span:

    - ``on_start``    -- opens the span; optionally records args.
    - ``on_success``  -- attaches the result and any
      ``extract_attributes`` output, then closes the span.
    - ``on_failure``  -- attaches the error type + message, then
      closes the span as a failure.

    Args:
        logfire_instance: A ``logfire.Logfire`` instance. ``None``
            uses the module-level default.
        span_name: Either a static string or a callable
            ``(ctx) -> str``. Default: ``ctx.func_name``.
        extract_attributes: Optional ``(ctx) -> dict`` called on
            success to add extra attributes to the span.
        log_args: When True, record ``ctx.args`` / ``ctx.kwargs`` on
            ``on_start``.
        log_result: When True, record ``ctx.result`` on ``on_success``.
        tags: Static tags applied to every span.

    Inherits the ``measurement`` / ``update_event`` / ``reset_event``
    channels from :class:`Meter` for symmetry with the other meters,
    but does not call ``update()`` itself -- Logfire is the sink.
    """

    name = "logfire"

    def __init__(
        self,
        logfire_instance: Any | None = None,
        span_name: str | Callable[[Context], str] | None = None,
        extract_attributes: Callable[[Context], dict[str, Any]] | None = None,
        log_args: bool = False,
        log_result: bool = False,
        tags: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._logfire = logfire_instance or _logfire
        self._span_name = span_name
        self._extract_attributes = extract_attributes
        self._log_args = log_args
        self._log_result = log_result
        self._tags = list(tags) if tags else []
        # Open spans keyed by id(ctx); a task's lifecycle is on one
        # thread per call, but multiple concurrent tasks each need
        # their own span entry. id(ctx) is unique per call.
        self._active_spans: dict[int, Any] = {}
        self._lock = threading.Lock()

    def _resolve_name(self, ctx: Context) -> str:
        if self._span_name is None:
            return ctx.func_name
        if callable(self._span_name):
            return self._span_name(ctx)
        return self._span_name

    def _logfire_handle(self) -> Any:
        if self._tags:
            return self._logfire.with_tags(*self._tags)
        return self._logfire

    def on_start(self, ctx: Context) -> None:
        attrs: dict[str, Any] = {}
        if self._log_args:
            args = getattr(ctx, "args", ())
            kwargs = getattr(ctx, "kwargs", {})
            attrs["args"] = repr(args) if args else None
            attrs["kwargs"] = repr(kwargs) if kwargs else None

        span = self._logfire_handle().span(self._resolve_name(ctx), **attrs)
        span.__enter__()
        with self._lock:
            self._active_spans[id(ctx)] = span

    def _close_span(self, ctx: Context) -> None:
        with self._lock:
            span = self._active_spans.pop(id(ctx), None)
        if span is None:
            return
        is_success = ctx.error is None
        try:
            if self._extract_attributes and is_success:
                try:
                    extra = self._extract_attributes(ctx) or {}
                    if extra:
                        span.set_attribute("result_attributes", extra)
                except Exception:
                    # An attribute extractor must not break the span.
                    pass
            if self._log_result and getattr(ctx, "result", None) is not None:
                span.set_attribute("result", repr(ctx.result))
            if not is_success and ctx.error is not None:
                span.set_attribute("error", str(ctx.error))
                span.set_attribute("error_type", type(ctx.error).__name__)
            # execution_time is on ExecutionContext; TaskContext shares the
            # same field via the Context union.
            exec_time = getattr(ctx, "execution_time", None)
            if exec_time is not None:
                span.set_attribute("execution_time", exec_time)
        finally:
            if ctx.error is not None:
                tb = getattr(ctx.error, "__traceback__", None)
                span.__exit__(type(ctx.error), ctx.error, tb)
            else:
                span.__exit__(None, None, None)

    def on_success(self, ctx: Context) -> None:
        # Don't aggregate -- Logfire is the sink, not the running mean.
        # Skip the Meter superclass's update / measurement.fire path.
        self._close_span(ctx)

    def on_failure(self, ctx: Context) -> None:
        self._close_span(ctx)


# Back-compat alias for code that imported the old name.
LogfireObserver = LogfireMeter


class LogfireMetricLogger:
    """Standalone helper for ad-hoc metric dicts.

    Useful inside training loops where you don't need full task
    lifecycle but want to push per-epoch / per-batch metrics::

        metric_logger = LogfireMetricLogger(prefix="train")

        for epoch in range(100):
            loss = train_one_epoch()
            metric_logger.log(epoch=epoch, loss=loss, accuracy=acc)

    Emits a Logfire info message with the kwargs as structured
    attributes.
    """

    def __init__(
        self,
        logfire_instance: Any | None = None,
        prefix: str = "metrics",
        tags: list[str] | None = None,
    ) -> None:
        handle = logfire_instance or _logfire
        if tags:
            handle = handle.with_tags(*tags)
        self._logfire = handle
        self._prefix = prefix

    def log(self, **kwargs: Any) -> None:
        msg = f"{self._prefix}: " + " ".join(f"{k}={v}" for k, v in kwargs.items())
        self._logfire.info(msg, **kwargs)
