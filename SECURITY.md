# Security policy

## Reporting a vulnerability

Please report security issues by email to **adnanharundogan@gmail.com**
with the subject prefix `[eventforge security]`. Do NOT open a public
GitHub issue.

You should expect an acknowledgement within 7 days. A fix and a
public disclosure date will be coordinated once the issue is
confirmed.

## Threat model

eventforge ships network-facing transports (`TCPServerTransport`,
`RPCServer`). They are intended for **trusted networks** -- a private
cluster network, a Docker bridge, an SSH-tunneled localhost. Treat
the TCP listener like an internal admin RPC: if the network reachable
from its bind address is hostile, so is the listener.

### Known unsafe surfaces

| surface | risk | mitigation |
|---|---|---|
| `TCPServerTransport` | No authentication, no transport encryption. Anyone who can reach the bound address can invoke any registered RPC method. | Default `host="127.0.0.1"` keeps the listener on loopback; multi-host setups should use SSH port forwarding or a reverse proxy that terminates TLS + auth. Do not pass `host="0.0.0.0"` unless every network reachable from that address is trusted. |
| Unbounded message queues | A single client can publish to many distinct topics, growing `_queues` without bound. Memory pressure / OOM. | Set `MessageQueue(max_queue_size=...)` to a reasonable ceiling. |
| RPC method dispatch | Whatever you register via `RPCServer.add_method` is callable by any caller that reaches the transport. | Register only methods that are safe to expose. Treat them like HTTP endpoints. |
| Pydantic deserialization | `Message` and `RPCRequest` are validated by Pydantic; the schema is closed, but a determined attacker can still attempt resource exhaustion (deep nesting, huge strings). | Keep the listener on a trusted network. Pydantic-v2's parsing is bounded but not infinitely so. |

### What does NOT cross a trust boundary

- In-process `Observable` / `Eventful` / `Dispatcher` -- pure Python
  callbacks, no network, no pickle.
- `MemoryTransport` -- single-process queue; no network exposure.
- `Meter` aggregators, `Reporter` subscribers (apart from
  `SyslogReporter` if you use it -- writes to the local syslog
  daemon, no network).

## Supported versions

Only the latest minor release receives security patches. Pre-1.0
releases may carry breaking changes between minor versions.
