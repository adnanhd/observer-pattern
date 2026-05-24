# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
post-1.0. Pre-1.0 minor versions may carry breaking changes.

## [0.1.0] -- 2026-05-24

First public release under the name **eventforge**. Source history
prior to this tag carried the working name `callpyback`; PyPI's
`callpyback` distribution belongs to an unrelated callback-decorator
library by another author. Renamed to remove the collision -- the
import name `callpyback` is gone, replaced by `eventforge`.

### Added

- **Unified observability primitive** (`eventforge.observers`):
  `Observable` + `Eventful` + `Dispatcher` -- one model that covers
  in-process pub-sub, work queues, cross-process RPC, parallel
  fan-out, and resource-aware load balancing.
- **Meters + Reporters**: `Meter` (an `Observable` that aggregates +
  emits) and `Reporter` (auto-wires via `@observe(MeterCls,
  "measurement")`). Built-ins: `TimingMeter`, `MemoryMeter`,
  `CPUMeter`, `MetricsMeter`, `LoggingReporter`.
- **Dispatchers**: `BroadcastDispatcher`, `RoundRobinDispatcher`,
  `ConcurrentDispatcher`, `LeastLoadedDispatcher`.
- **Transports**: `MemoryTransport` (in-process) and
  `TCPServerTransport` / `TCPClientTransport` (across process).
- **Queues**: `MessageQueue` for pub-sub, `WorkQueue` for competing
  consumers with retries + dead-letter routing.
- **RPC**: `RPCServer` / `RPCClient` over any `Transport`.
- **Executor + task decorator**: `Executor` runs callables in three
  modes (sync, thread, process); `@task` wraps a function as a
  runnable + observable unit.
- **Logfire integration**: `LogfireMeter` opens a Pydantic Logfire
  span per task execution; `LogfireMetricLogger` for ad-hoc metric
  dicts.
- **`py.typed` marker** so downstream `mypy` / `pyright` consumers
  pick up the type hints.
- **Release workflow**: tag-push triggers sdist + wheel build, twine
  check, PyPI publish via trusted publishing, GitHub release.

### Changed

- **Project renamed** from `callpyback` to `eventforge`. The PyPI
  distribution name, the package directory, and the import name all
  change in lockstep. Downstream consumers need to update both their
  `pyproject.toml` and their `from callpyback import ...` lines.
- **`TCPServerTransport.host` default changed** from `"0.0.0.0"` to
  `"127.0.0.1"`. The previous default exposed an unauthenticated RPC
  listener to every interface. Multi-host setups now opt in
  explicitly; SSH tunnel / reverse proxy is the documented path. See
  `SECURITY.md`.

### Removed

- Stale `[redis]` and `[zmq]` optional extras -- neither transport
  was implemented.
- Top-level `requirements.txt` -- it pinned dev-only artefacts
  (`black==23.1.0`, `coveralls`, etc.) and contradicted
  `pyproject.toml`'s `[dev]` extra. Use `pip install -e ".[dev]"`
  instead.

### Fixed

- `LogfireObserver` (now `LogfireMeter`) ported from the removed
  `Observer` lifecycle base to the new `Meter` class; the previous
  refactor that introduced `Meter` / `Reporter` had left this
  integration broken at import time.
- README, all `docs/*.md`, and three example scripts (`03_observers`,
  `04_task_decorator`, `05_full_example`) referenced the deleted
  `*Observer` class names (`TimingObserver`, `MetricsObserver`,
  `LoggingObserver`, `MemoryObserver`, `CPUObserver`, `MeterObserver`).
  All renamed to `TimingMeter` / `MetricsMeter` / `LoggingReporter` /
  `MemoryMeter` / `CPUMeter` / `Meter`. README RPC snippet now uses
  the real `server.serve()` (was `server.start()` -- no such method).
- Version reconciled to 0.1.0 across `pyproject.toml` and
  `eventforge/__init__.py` (was 3.0.0 vs 4.0.0).
- `pyrightconfig.json` no longer carries the developer's local conda
  prefix path.

[0.1.0]: https://github.com/adnanhd/eventforge/releases/tag/v0.1.0
