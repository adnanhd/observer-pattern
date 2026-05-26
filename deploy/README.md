# Deploying eventforge: server/demander topology

eventforge has no daemon of its own -- it's a library. The one shape
worth containerizing is an **eventforge-network**: a pool of RPC
*server* nodes each running `python -m eventforge.worker`, and one or
more *demander* (client) nodes that round-robin calls across them.

```
demander  --RPC (length-prefixed JSON over TCP)-->  server1
                                              \-->  server2
                                              \-->  server3
```

This is `examples/07_distributed_workers.py` productionized: instead of
the driver spawning worker subprocesses from an inlined source string,
each server is its own container/SIF running the generic worker
entrypoint against a handler module.

## What this is (and is not)

- **Is:** an RPC compute-worker pool for a trusted network (docker/k8s
  internal, HPC interconnect). Request/response, client-side round-robin.
- **Is not:** a job queue. `WorkQueue`'s competing-consumer + ack/nack +
  DLQ are **in-process only** -- they do not cross container boundaries.
  Load balancing is client-side: the demander must know every server
  address (no broker, no service discovery). The TCP transport has **no
  auth and no TLS** -- never bind it to a public interface.

For durable, brokered job queues across machines, reach for Celery / RQ
/ Dramatiq. eventforge's niche here is coherence: if you already use it
for in-process dispatch and the registry-pattern envelope, this scales
that *same* code across nodes without adding a second framework.

## The worker entrypoint

```bash
python -m eventforge.worker --import handlers --service math --port 9090
```

The `--import`ed module must expose:

```python
def compute(x): ...
HANDLERS = {"compute": compute}   # required: name -> callable
SERVICE_NAME = "math"             # optional (default "rpc"); --service overrides
```

See [`topology/handlers.py`](topology/handlers.py) for the demo module
and [`topology/demander.py`](topology/demander.py) for the client.

## Run the topology locally (Docker)

```bash
docker compose -f deploy/docker-compose.yml up --build
```

Three servers come up; the demander connects to all three and fires 12
`compute` calls. Its logs show the calls spread evenly across servers:

```
demander: load distribution by server:
  server1: 4 calls
  server2: 4 calls
  server3: 4 calls
```

Add more `serverN` services and list them in the demander's
`EVENTFORGE_SERVERS` to grow the pool. Edit `topology/handlers.py` and
re-run -- it's bind-mounted, so no rebuild is needed.

## Single server (Docker)

```bash
docker build -f deploy/Dockerfile -t eventforge:latest .
docker run --rm -p 9090:9090 \
  -v "$(pwd)/deploy/topology":/work -e PYTHONPATH=/work \
  eventforge:latest --import handlers --service math --port 9090
```

## HPC (Apptainer / Singularity)

See [`apptainer/eventforge.def`](apptainer/eventforge.def) -- same stack,
for running servers as compute-node jobs with the demander on the login
node.
