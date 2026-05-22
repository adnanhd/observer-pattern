"""Event-driven observability + dispatch.

Single mechanism (``Observable`` + ``Eventful`` + ``Dispatcher``) covers every
flow callpyback supports: in-process pub-sub, cross-process RPC, work queues
with ack/nack, parallel fanout, resource-aware load balancing.

Core concepts
-------------

``Observable``      Umbrella class holding N ``Eventful`` channels as
                    attributes. Provides string-keyed ``.on()/.fire()`` that
                    route to attribute Eventfuls -- so ``task.on("success",
                    fn)`` and ``task.success.on(fn)`` are equivalent.

``Eventful``        A single pub-sub channel: subscriber list + Dispatcher.
                    ``.on(fn)`` subscribes, ``.fire(*args)`` invokes the
                    Dispatcher with the subscriber list.

``Dispatcher``      Delivery policy. The actual VALUE callpyback adds beyond
                    a plain event bus. Choose Broadcast / RoundRobin /
                    Concurrent / Queue / Transport / LeastLoaded /
                    ResourceAware as the run-time backing.

``Node``            Subscriber wrapper with resource metadata (cpus, memory,
                    gpus, handler) + load metric. Used by resource-aware
                    dispatchers for cluster-style scheduling.

``Meter``           ``Observable`` subclass with running-average state
                    (val/avg/sum/count) + ``on_start`` / ``on_success`` /
                    ``on_failure`` / ``on_complete`` convention methods.
                    Auto-emits ``"measurement"`` after each ``on_success``.

``Reporter``        ``Observable`` subclass that auto-subscribes methods
                    marked with ``@observe(MeterCls, "event")`` at
                    ``__init__`` -- not a task lifecycle listener, only
                    reacts to upstream Meter emissions.

Lifecycle event names (extensible; just call ``self.fire("name", ...)``):

    "start"      mirrors ``try:`` (before body)
    "success"    mirrors ``else:`` (clean completion)
    "failure"    mirrors ``except:`` (exception path)
    "complete"   mirrors ``finally:`` (always runs)
"""

from __future__ import annotations

import functools
import logging
import resource
import threading
import time
import tracemalloc
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Dict, List, Optional, Union

from callpyback.types import TaskContext

logger = logging.getLogger(__name__)


# =============================================================================
# Execution context
# =============================================================================


@dataclass
class ExecutionContext:
    """Context passed to listeners during execution.

    Compatible with :class:`callpyback.types.TaskContext` for fields that
    overlap (func_name, args, kwargs, result, error, metadata, ...). Use the
    :class:`Context` alias below for type hints that accept either.
    """

    func_name: str
    args: tuple
    kwargs: Dict[str, Any]
    start_time: float = 0.0
    end_time: float = 0.0
    result: Any = None
    error: Optional[Exception] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def execution_time(self) -> float:
        return self.end_time - self.start_time if self.end_time else 0.0

    @property
    def is_success(self) -> bool:
        return self.error is None


Context = Union[ExecutionContext, TaskContext]


# =============================================================================
# Dispatcher -- delivery policy
# =============================================================================


class Dispatcher(ABC):
    """How an ``Eventful.fire()`` reaches its subscribers.

    Subclasses implement the actual routing: broadcast to all, round-robin
    one at a time, concurrent fanout via an executor pool, push to a queue
    for competing consumers, send over a transport for cross-process
    delivery, or anything else.
    """

    @abstractmethod
    def dispatch(
        self,
        subscribers: List[Callable],
        args: tuple,
        kwargs: Dict[str, Any],
    ) -> None: ...


class BroadcastDispatcher(Dispatcher):
    """Default: call every subscriber in order; swallow each one's exceptions."""

    def dispatch(self, subscribers, args, kwargs):
        for fn in subscribers:
            try:
                fn(*args, **kwargs)
            except Exception:
                logger.exception("broadcast subscriber failed: %r", fn)


class RoundRobinDispatcher(Dispatcher):
    """One subscriber per fire, rotating through the list.

    Use when subscribers are competing workers and each event should land on
    exactly ONE worker.
    """

    def __init__(self) -> None:
        self._idx = 0
        self._lock = threading.Lock()

    def dispatch(self, subscribers, args, kwargs):
        if not subscribers:
            return
        with self._lock:
            fn = subscribers[self._idx % len(subscribers)]
            self._idx += 1
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.exception("round-robin subscriber failed: %r", fn)


class ConcurrentDispatcher(Dispatcher):
    """Submit each subscriber to an executor pool (thread / process).

    Subscribers run in parallel; fire returns immediately.
    """

    def __init__(self, executor) -> None:
        self._executor = executor

    def dispatch(self, subscribers, args, kwargs):
        for fn in subscribers:
            try:
                self._executor.submit(fn, *args, **kwargs)
            except Exception:
                logger.exception("concurrent submit failed: %r", fn)


class LeastLoadedDispatcher(Dispatcher):
    """Ask each subscriber for its load and route to the least-loaded.

    Subscribers must expose ``load() -> float`` (e.g. :class:`Node`
    instances). Saturated subscribers (load >= 1.0) are skipped.
    """

    def dispatch(self, subscribers, args, kwargs):
        if not subscribers:
            return
        available = [(s, s.load()) for s in subscribers if s.load() < 1.0]
        if not available:
            raise RuntimeError("all subscribers saturated")
        pick = min(available, key=lambda x: x[1])[0]
        try:
            pick(*args, **kwargs)
        except Exception:
            logger.exception("least-loaded subscriber failed: %r", pick)


# =============================================================================
# Eventful -- a single pub-sub channel
# =============================================================================


class Eventful:
    """One named pub-sub channel: subscribers + Dispatcher.

    Owned by an :class:`Observable` as an attribute. Subscribers register
    via ``.on(fn)`` / ``.subscribe(fn)`` and run when ``.fire(*args, **kw)``
    is called (routed through the channel's :class:`Dispatcher`).

    If constructed with ``owner`` + ``name`` (typically done by Observable
    subclasses), ``fire`` ALSO dispatches to class-level subscribers
    registered via :func:`observe` against any class in the owner's MRO.
    This is the mechanism behind :class:`Reporter`'s auto-wiring.
    """

    def __init__(
        self,
        dispatcher: Optional[Dispatcher] = None,
        *,
        owner: Optional["Observable"] = None,
        name: Optional[str] = None,
    ) -> None:
        self._subscribers: List[Callable] = []
        self._dispatcher = dispatcher or BroadcastDispatcher()
        self._lock = threading.Lock()
        # When owner+name are set, fire() also walks owner's MRO for
        # class-level subscribers. Avoids the previous monkey-patch
        # approach where Meter.__init__ was rewritten to wrap channel.fire.
        self._owner = owner
        self._name = name

    def subscribe(self, fn: Callable) -> Callable:
        """Register ``fn`` to receive every fire on this channel. Returns ``fn``."""
        with self._lock:
            self._subscribers.append(fn)
        return fn

    # Convenience alias.
    on = subscribe

    def unsubscribe(self, fn: Callable) -> bool:
        with self._lock:
            try:
                self._subscribers.remove(fn)
                return True
            except ValueError:
                return False

    def fire(self, *args: Any, **kwargs: Any) -> None:
        """Dispatch to instance subscribers (via Dispatcher) and then to
        class-level subscribers registered via :func:`observe`, if this
        Eventful was constructed with ``owner`` + ``name``.
        """
        with self._lock:
            subs = list(self._subscribers)
        self._dispatcher.dispatch(subs, args, kwargs)

        if self._owner is not None and self._name is not None:
            for klass in type(self._owner).__mro__:
                if klass is object:
                    continue
                cls_subs = _CLASS_SUBSCRIBERS.get(klass, {}).get(self._name)
                if not cls_subs:
                    continue
                for fn in cls_subs:
                    try:
                        fn(*args, **kwargs)
                    except Exception:
                        logger.exception(
                            "class subscriber for %s.%s failed: %r",
                            klass.__name__,
                            self._name,
                            fn,
                        )

    @property
    def subscribers(self) -> List[Callable]:
        with self._lock:
            return list(self._subscribers)

    def set_dispatcher(self, dispatcher: Dispatcher) -> None:
        self._dispatcher = dispatcher


# =============================================================================
# Observable -- container of Eventful attributes
# =============================================================================


class Observable:
    """Umbrella: container of multiple :class:`Eventful` channels.

    Subclasses declare channels in ``__init__`` (or via class-level Eventful
    attributes initialized in __init_subclass__). Subscribers can access
    channels two equivalent ways:

      * Attribute style (typo-safe, IDE-friendly)::

            obj.success.on(handler)
            obj.success.fire(ctx)

      * String style (dynamic, config-driven)::

            obj.on("success", handler)
            obj.fire("success", ctx)

    The string form looks up the attribute, asserts it is an Eventful, and
    delegates to it. ``AttributeError`` raised if no such Eventful exists.
    """

    def on(self, event: str, fn: Callable) -> Callable:
        target = getattr(self, event, None)
        if not isinstance(target, Eventful):
            raise AttributeError(
                f"{type(self).__name__} has no Eventful attribute {event!r}"
            )
        return target.subscribe(fn)

    subscribe = on  # alias

    def fire(self, event: str, *args: Any, **kwargs: Any) -> None:
        target = getattr(self, event, None)
        if not isinstance(target, Eventful):
            raise AttributeError(
                f"{type(self).__name__} has no Eventful attribute {event!r}"
            )
        target.fire(*args, **kwargs)

    def events(self) -> List[str]:
        """List of Eventful attribute names on this instance."""
        return [
            name
            for name in dir(self)
            if not name.startswith("_")
            and isinstance(getattr(self, name, None), Eventful)
        ]


# =============================================================================
# Node -- subscriber with resource metadata + load metric
# =============================================================================


@dataclass
class Node:
    """Worker unit: capacity + handler + load tracking.

    Used as a subscriber in resource-aware dispatchers. The ``handler``
    is the actual callable to invoke (a local function, a GPU worker, an
    RPC client, ...). ``load()`` reports current utilization in [0, 1].

    Subclass :class:`LocalNode` for in-process workers (counter-based),
    :class:`RemoteNode` for RPC-backed workers (query the remote side).
    """

    name: str
    cpus: int
    memory_gb: float
    gpus: List[int]
    handler: Callable
    _in_flight: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            self._in_flight += 1
        try:
            return self.handler(*args, **kwargs)
        finally:
            with self._lock:
                self._in_flight -= 1

    @property
    def capacity(self) -> int:
        """How many concurrent tasks this node can handle. Default: 1 per GPU,
        or cpus // 4 for CPU-only."""
        return len(self.gpus) or max(self.cpus // 4, 1)

    def load(self) -> float:
        """Current utilization in [0, 1]. Override for remote/active query."""
        with self._lock:
            return self._in_flight / self.capacity


# =============================================================================
# Meter -- Observable + aggregator + lifecycle convention
# =============================================================================


class Meter(Observable):
    """Aggregator + lifecycle observer + emission source.

    Three roles in one:

    1. **Aggregator** -- running average across calls. ``update(val, n)``
       maintains ``val / avg / sum / count``; fires ``self.update_event``
       on each update.

    2. **Lifecycle observer** -- ``attach(source)`` subscribes
       ``self.on_start`` / ``on_success`` / ``on_failure`` / ``on_complete``
       to the matching events on ``source``. Subclasses override
       ``measure(ctx) -> Optional[float]`` to compute one observation per
       task call; the default ``on_success`` calls ``measure``, updates
       the aggregator, and fires ``self.measurement``.

    3. **Emission source** -- ``self.measurement`` and ``self.update_event``
       are :class:`Eventful` channels Reporters can subscribe to.
    """

    name: ClassVar[str] = "meter"

    def __init__(
        self,
        name: Optional[str] = None,
        dispatcher: Optional[Dispatcher] = None,
    ) -> None:
        if name is not None:
            self.name = name
        # Emission channels
        # owner+name make these Eventfuls class-subscriber-aware: when fire
        # is called, the Eventful walks ``type(self).__mro__`` looking for
        # class-level subscribers registered via :func:`observe`. No
        # monkey-patching required.
        self.measurement = Eventful(
            dispatcher=dispatcher, owner=self, name="measurement"
        )
        self.update_event = Eventful(
            dispatcher=dispatcher, owner=self, name="update_event"
        )
        self.reset_event = Eventful(
            dispatcher=dispatcher, owner=self, name="reset_event"
        )
        # Aggregator state
        self.reset()

    # ---- aggregator ----------------------------------------------------

    def reset(self) -> None:
        self.val: float = 0.0
        self.avg: float = 0.0
        self.sum: float = 0.0
        self.count: int = 0
        self.reset_event.fire(self)

    def update(self, val: float, n: int = 1) -> None:
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count if self.count > 0 else 0.0
        self.update_event.fire(self, val, n)

    @property
    def stats(self) -> Dict[str, float]:
        return {"val": self.val, "avg": self.avg, "sum": self.sum, "count": self.count}

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name}: avg={self.avg:.4f}, count={self.count})"

    # ---- lifecycle convention ------------------------------------------

    def measure(self, ctx: Context) -> Optional[float]:
        """Compute one observation per task call. Default no-op."""
        return None

    def on_start(self, ctx: Context) -> None:
        """try: -- before body."""

    def on_success(self, ctx: Context) -> None:
        """else: -- clean completion. Measures + updates + emits."""
        val = self.measure(ctx)
        if val is not None:
            self.update(val)
        ctx.metadata[self.name] = val
        self.measurement.fire(self, val, ctx)

    def on_failure(self, ctx: Context) -> None:
        """except: -- exception path. Default no-op (no measurement on failure)."""

    def on_complete(self, ctx: Context) -> None:
        """finally: -- always. Default no-op."""

    def attach(self, source: Observable) -> "Meter":
        """Wire each ``on_<event>`` method as a subscriber to ``source.<event>``.

        Convention: method ``on_X`` -> subscribed to event ``"X"``. Returns
        ``self`` for chaining (``Meter().attach(task)``).

        The ``on_X`` method scan is cached per Meter subclass via
        ``_meter_event_names`` so attach() runs in O(channels) rather than
        re-walking ``dir(type(self))`` on every call.
        """
        for attr in _meter_event_names(type(self)):
            method = getattr(self, attr)
            event = attr[3:]
            channel = getattr(source, event, None)
            if isinstance(channel, Eventful):
                channel.subscribe(method)
        return self


@functools.lru_cache(maxsize=None)
def _meter_event_names(meter_cls: type) -> tuple:
    """Cached scan of ``on_X`` callables on a Meter subclass.

    ``dir()`` + ``startswith`` cost ~43 string ops per attach for a typical
    Meter; that scan is identical across all instances of the same class
    and across repeated attaches of the same instance, so we memoize it.
    Keyed on the class itself; cache survives for the class's lifetime.
    """
    names = []
    for attr in dir(meter_cls):
        if not attr.startswith("on_"):
            continue
        method = getattr(meter_cls, attr, None)
        if callable(method):
            names.append(attr)
    return tuple(names)


# =============================================================================
# Reporter -- auto-wired subscribers via @observe markers
# =============================================================================


class Reporter(Observable):
    """Observable that auto-subscribes its decorated methods at ``__init__``.

    Methods marked with ``@observe(TargetCls, "event_name")`` are bound to
    ``self`` and subscribed to ``TargetCls.<event_name>`` for every instance
    of ``TargetCls``. Implementation: walks ``type(self)`` looking for
    ``_observe_targets`` markers placed by the decorator.

    Reporters react to upstream Meters (or any Observable). They are NOT
    task-lifecycle observers themselves.

    Example::

        class LoggingReporter(Reporter):
            @observe(Meter, "measurement")
            def log_measurement(self, meter, value, ctx):
                logger.info("%s = %s", meter.name, value)
    """

    def __init__(self) -> None:
        # No lifecycle channels by default; subclasses may add their own.
        # The walker runs unconditionally so subclasses' decorated methods
        # auto-wire without needing to call any specific super().
        for attr in dir(type(self)):
            method = getattr(type(self), attr, None)
            targets = getattr(method, "_observe_targets", None)
            if not targets:
                continue
            bound = getattr(self, attr)
            for target_cls, event in targets:
                _register_class_subscriber(target_cls, event, bound)


# Class-level subscriber registry: per (Observable subclass, event name)
# we keep a list of bound methods that should be invoked when any instance
# of that class fires the corresponding event. Consulted directly by
# :meth:`Eventful.fire` when the eventful was constructed with
# ``owner`` + ``name``.
_CLASS_SUBSCRIBERS: Dict[type, Dict[str, List[Callable]]] = {}


def _register_class_subscriber(target_cls: type, event: str, fn: Callable) -> None:
    _CLASS_SUBSCRIBERS.setdefault(target_cls, {}).setdefault(event, []).append(fn)


def observe(target_cls: type, event: str) -> Callable:
    """Mark a Reporter method as a class-level subscriber to
    ``target_cls.<event>``.

    The actual subscription happens at the Reporter instance's
    ``__init__``, which binds the method to ``self`` and registers it
    via :func:`_register_class_subscriber`. When any instance of
    ``target_cls`` (or a subclass) fires the matching event, the bound
    method is invoked.
    """

    def deco(fn: Callable) -> Callable:
        existing = list(getattr(fn, "_observe_targets", []))
        existing.append((target_cls, event))
        fn._observe_targets = existing  # type: ignore[attr-defined]
        return fn

    return deco


# =============================================================================
# Concrete meters
# =============================================================================


class TimingMeter(Meter):
    """Tracks per-call elapsed wall time."""

    name = "timing"

    def __init__(self, threshold: Optional[float] = None, name: str = "timing") -> None:
        super().__init__(name=name)
        self.threshold = threshold

    def on_start(self, ctx: Context) -> None:
        ctx.metadata[f"{self.name}_start"] = time.perf_counter()

    def measure(self, ctx: Context) -> float:
        start = ctx.metadata.get(f"{self.name}_start", ctx.start_time)
        elapsed = time.perf_counter() - start
        if self.threshold and elapsed > self.threshold:
            ctx.metadata[f"{self.name}_exceeded"] = True
        return elapsed


class MemoryMeter(Meter):
    """Tracks per-call memory delta via :mod:`tracemalloc`."""

    name = "memory"

    def __init__(self, name: str = "memory") -> None:
        super().__init__(name=name)

    def on_start(self, ctx: Context) -> None:
        if not tracemalloc.is_tracing():
            tracemalloc.start()
        current, _peak = tracemalloc.get_traced_memory()
        ctx.metadata[f"{self.name}_start"] = current

    def measure(self, ctx: Context) -> float:
        current, peak = tracemalloc.get_traced_memory()
        start = ctx.metadata.get(f"{self.name}_start", 0)
        ctx.metadata[f"{self.name}_peak"] = peak
        return float(current - start)


class CPUMeter(Meter):
    """Tracks per-call user+system CPU time via :func:`resource.getrusage`."""

    name = "cpu"

    def __init__(self, name: str = "cpu") -> None:
        super().__init__(name=name)

    def on_start(self, ctx: Context) -> None:
        ru = resource.getrusage(resource.RUSAGE_SELF)
        ctx.metadata[f"{self.name}_start"] = ru.ru_utime + ru.ru_stime

    def measure(self, ctx: Context) -> float:
        ru = resource.getrusage(resource.RUSAGE_SELF)
        start = ctx.metadata.get(f"{self.name}_start", 0.0)
        return float((ru.ru_utime + ru.ru_stime) - start)


class MetricsMeter(Meter):
    """Pulls a single numeric metric from ``ctx.result`` via an extractor fn."""

    def __init__(
        self,
        name: str,
        extract: Callable[[Context], Optional[float]],
    ) -> None:
        super().__init__(name=name)
        self._extract = extract

    def measure(self, ctx: Context) -> Optional[float]:
        try:
            return self._extract(ctx)
        except Exception:
            return None


# =============================================================================
# Concrete reporters
# =============================================================================


class LoggingReporter(Reporter):
    """Logs every Meter's ``measurement`` event via stdlib logging.

    Subscribes to :class:`Meter` (MRO walk catches all subclasses), so a
    single ``LoggingReporter()`` reports for every Meter instance in the
    process.
    """

    def __init__(
        self,
        level: int = logging.INFO,
        log_args: bool = False,
        log_result: bool = False,
        logger_name: str = "callpyback",
    ) -> None:
        self._level = level
        self._log_args = log_args
        self._log_result = log_result
        self._log = logging.getLogger(logger_name)
        super().__init__()

    @observe(Meter, "measurement")
    def _on_measurement(self, meter: Meter, value: Any, ctx: Context) -> None:
        msg = f"{meter.name} = {value}"
        if self._log_args:
            msg += f" args={ctx.args!r} kwargs={ctx.kwargs!r}"
        if self._log_result:
            msg += f" result={ctx.result!r}"
        self._log.log(self._level, msg)
