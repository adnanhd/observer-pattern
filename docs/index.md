# eventforge Documentation

Message-driven task execution with pub-sub, executors, and RPC.

## Overview

eventforge is a Python library for building message-driven applications. The
mental model is a 2x2 of *what kind of exchange* (pub-sub fire-and-forget vs
request-reply) by *where the other side lives* (local vs remote):

|                  | local          | remote        |
|------------------|----------------|---------------|
| **pub-sub**      | `MessageQueue` | `RemoteQueue` |
| **request-reply**| `Executor`     | RPC (`RPCServer` / `RPCClient`) |

`Executor` runs work in-process; RPC runs it on another process or machine,
called by name. The `Transport` (Memory or TCP) is *where* local-vs-remote
lives. `@task` composes an `Executor` + a `MessageQueue` + `Observers`.

- **Message Queue**: local pub-sub messaging with Pydantic validation
- **Remote Queue**: push-only switchboard for cross-node pub-sub
- **Executor**: local request-reply -- run work in sequential, thread, or process mode
- **RPC**: remote request-reply over a message queue (`RPCClient.call(name, ...)` invokes a method registered on an `RPCServer`)
- **Task Decorator**: facade composing a runner + queue + observers
- **Observers**: profile and monitor task execution

## Installation

```bash
pip install eventforge
```

Core install pulls only `pydantic` + `typing-extensions`. The Memory and TCP
transports are stdlib. Optional extras: `eventforge[redis]` /
`eventforge[nats]` for the broker-backed transports, `eventforge[logfire]`
for Logfire emission.

## Quick Start

```python
from eventforge import task, MessageQueue, Executor, ExecutionMode, TimingMeter

queue = MessageQueue()
timing = TimingMeter()

# Task with full lifecycle support
@task(
    queue=queue,
    topic="process.data",
    on_execute=[timing],
    on_success=lambda ctx: print(f"Done: {ctx.result}"),
)
def process_data(data):
    return data.upper()

# Direct call - returns result
result = process_data("hello")  # "HELLO"

# Queue trigger - same execution path
queue.publish("process.data", "world")

# Check timing stats
print(timing.stats)  # {'count': 2, 'avg': 0.001, ...}

# Parallel execution
with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
    results = executor.map(lambda x: x ** 2, [1, 2, 3, 4, 5])
```

## Execution Flow Diagrams

### Task Execution Lifecycle

```mermaid
flowchart TD
    A["process_data('hello')"] --> B["TaskRunner.run()"]
    B --> C["Acquire pool slot\n(if max_instances set)"]
    C --> D["Create TaskContext\n(task_id, args, start_time)"]
    D --> E["observer.on_start(ctx)\nfor each observer"]
    E --> F{Execution Mode}
    F -->|SEQUENTIAL| G["result = func(*args)"]
    F -->|THREAD| H["executor.submit(func)"]
    F -->|PROCESS| I["executor.submit(func)"]
    H --> J["executor.result(task_id)"]
    I --> J
    G --> K{Success?}
    J --> K
    K -->|Yes| L["observer.on_end(ctx)"]
    K -->|No| M["observer.on_error(ctx)"]
    L --> N["on_success(ctx)"]
    M --> O["on_failure(ctx)"]
    N --> P["publish '{topic}.success'"]
    O --> Q["publish '{topic}.failure'"]
    P --> R["on_complete(ctx)"]
    Q --> R
    R --> S["Release pool slot"]
    S --> T["Return result"]
    Q --> U["Re-raise exception"]

    style A fill:#4a9eff,color:#fff
    style T fill:#22c55e,color:#fff
    style U fill:#ef4444,color:#fff
```

### Queue-Triggered Execution

```mermaid
flowchart LR
    A["queue.publish\n('process.data', payload)"] --> B["Create Message"]
    B --> C["transport.send(msg)"]
    C --> D["MemoryTransport"]
    D --> E["Find subscribers\nfor topic"]
    E --> F["callback(msg)"]
    F --> G["@queue.on handler\nextracts payload"]
    G --> H["process_data(payload)"]
    H --> I["TaskRunner.run()\n(same lifecycle)"]

    style A fill:#4a9eff,color:#fff
    style I fill:#22c55e,color:#fff
```

### Observer Notification Order

```mermaid
sequenceDiagram
    participant T as TaskRunner
    participant Ti as TimingMeter
    participant Me as MetricsMeter
    participant Mo as MemoryMeter
    participant F as Function

    T->>Ti: on_start(ctx)
    Ti->>Ti: record start time
    T->>Me: on_start(ctx)
    Me->>Me: increment call count
    T->>Mo: on_start(ctx)
    Mo->>Mo: take memory snapshot

    T->>F: execute func(*args)
    F-->>T: result / exception

    alt Success
        T->>Ti: on_end(ctx)
        Ti->>Ti: record elapsed, check threshold
        T->>Me: on_end(ctx)
        Me->>Me: increment success count
        T->>Mo: on_end(ctx)
        Mo->>Mo: record memory delta
    else Failure
        T->>Ti: on_error(ctx)
        T->>Me: on_error(ctx)
        Me->>Me: increment failure count
        T->>Mo: on_error(ctx)
    end
```

### RPC Request-Reply Flow

```mermaid
sequenceDiagram
    participant C as RPCClient
    participant Q as MessageQueue
    participant S as RPCServer

    C->>C: Create RPCRequest(method, args)
    C->>C: Generate unique reply_to topic
    C->>Q: publish("service.request", request)
    Q->>S: deliver message

    S->>S: Parse RPCRequest
    S->>S: Lookup method in _methods
    S->>S: Execute method(*args, **kwargs)
    S->>S: Create RPCResponse(result)
    S->>Q: publish(reply_to, response)
    Q->>C: deliver response

    C->>C: Extract result from RPCResponse
    C-->>C: Return result
```

### RemoteQueue Push-Only Switchboard

```mermaid
flowchart LR
    subgraph Coord["Coordinator (sender)"]
        RQ1["RemoteQueue\ncoordinator"]
        T1["TCPClientTransport\n(owned per peer)"]
        RQ1 --- T1
    end

    subgraph Worker["Worker (receiver)"]
        RQ2["RemoteQueue\nworker-1"]
        LQ["local MessageQueue\n(TCPServerTransport)"]
        H["@worker.on('work')\nhandler"]
        RQ2 --- LQ
        LQ --- H
    end

    RQ1 -->|"send('worker-1', 'work', payload)\nbroadcast('work', payload)"| T1
    T1 -->|"JSON / TCP"| LQ

    style Coord fill:#f0f9ff,stroke:#4a9eff
    style Worker fill:#f0fdf4,stroke:#22c55e
```

A node owns one outbound TCP link per peer for `send` / `broadcast`, and
receives via an optional `local` MessageQueue that peers push into. It is
push-only: to pull a value from a peer, use RPC. See
[Remote Queue](remote.md).

## Modules

- [Task](task.md) - Unified task decorator with lifecycle support
- [Message Queue](queue.md) - Pub-sub messaging
- [Executor](executor.md) - Parallel task execution (local request-reply)
- [RPC](rpc.md) - Remote procedure calls
- [Remote Queue](remote.md) - Distributed messaging
- [Observers](observers.md) - Execution profiling
- [Types](types.md) - Pydantic models

## Architecture

```
eventforge/
  types.py          # Pydantic models (Message, TaskResult, TaskContext, etc.)
  transports/       # Message transport backends
    base.py         # Transport ABC
    memory.py       # In-memory transport (default)
    tcp.py          # JSON-over-TCP server/client transports
    redis.py        # Redis pub/sub transport (optional: [redis])
    nats.py         # NATS pub/sub transport (optional: [nats])
  queue.py          # MessageQueue with pub-sub
  remote.py         # RemoteQueue push-only switchboard
  executor.py       # Executor (local request-reply)
  rpc.py            # RPCServer and RPCClient (remote request-reply)
  task.py           # @task facade + TaskRunner
  observers.py      # Observable / Eventful / Dispatcher + Meters
  worker.py         # python -m eventforge.worker entrypoint
```

## License

MIT
