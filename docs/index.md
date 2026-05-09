# CallPyBack Documentation

Message-driven task execution with pub-sub, executors, and RPC.

## Overview

CallPyBack is a Python library for building message-driven applications with:

- **Task Decorator**: Unified task abstraction with lifecycle support
- **Message Queue**: Pub-sub messaging with Pydantic validation
- **Executor**: Run tasks in sequential, thread, or process mode
- **RPC**: Remote procedure calls over message queue
- **Remote Queue**: Bridge queues across distributed nodes
- **Observers**: Profile and monitor task execution

## Installation

```bash
pip install callpyback

# Optional transports
pip install callpyback[redis]
pip install callpyback[zmq]
```

## Quick Start

```python
from callpyback import task, MessageQueue, Executor, ExecutionMode, TimingObserver

queue = MessageQueue()
timing = TimingObserver()

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
    participant Ti as TimingObserver
    participant Me as MetricsObserver
    participant Mo as MemoryObserver
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

### Distributed RemoteQueue Bridging

```mermaid
flowchart TB
    subgraph Node1["Node 1"]
        RQ1["RemoteQueue\nnode-1"]
        Q1["MessageQueue"]
        RPC1["RPC Server\nremote.node-1"]
        RQ1 --- Q1
        RQ1 --- RPC1
    end

    subgraph Node2["Node 2"]
        RQ2["RemoteQueue\nnode-2"]
        Q2["MessageQueue"]
        RPC2["RPC Server\nremote.node-2"]
        RQ2 --- Q2
        RQ2 --- RPC2
    end

    RQ1 -->|"subscribe_remote\n('node-2', 'events.order')"| RPC2
    RPC2 -->|"forward matching\nmessages"| Q1
    RQ2 -->|"publish\n('events.order', data)"| Q2
    Q2 -.->|"trigger forward\nvia subscription"| RPC2

    style Node1 fill:#f0f9ff,stroke:#4a9eff
    style Node2 fill:#f0fdf4,stroke:#22c55e
```

## Modules

- [Task](task.md) - Unified task decorator with lifecycle support
- [Message Queue](queue.md) - Pub-sub messaging
- [Executor](executor.md) - Parallel task execution
- [RPC](rpc.md) - Remote procedure calls
- [Remote Queue](remote.md) - Distributed messaging
- [Observers](observers.md) - Execution profiling
- [Types](types.md) - Pydantic models

## Architecture

```
callpyback/
├── types.py          # Pydantic models (Message, TaskResult, TaskContext, etc.)
├── transports/       # Message transport backends
│   ├── base.py       # Transport protocol
│   └── memory.py     # In-memory transport
├── queue.py          # MessageQueue with pub-sub
├── executor.py       # Unified Executor
├── task.py           # @task decorator and TaskRunner
├── rpc.py            # RPCServer and RPCClient
├── remote.py         # RemoteQueue for distributed messaging
└── observers.py      # Execution observers and Meter
```

## License

MIT
