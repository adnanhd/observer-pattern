# eventforge worker image -- pure-Python, no GPU/heavy deps.
#
# Core eventforge pulls only pydantic; the TCP transport is stdlib. This
# image is the "server" node in an eventforge-network topology: it runs
# `python -m eventforge.worker` against a handler module you mount in.
#
# Build from the repository root:
#   docker build -f deploy/Dockerfile -t eventforge:latest .
#
# Run a server (mount your handlers, expose the port):
#   docker run --rm -p 9090:9090 \
#     -v "$(pwd)/deploy/topology":/work -e PYTHONPATH=/work \
#     eventforge:latest --import handlers --service math --port 9090
#
# Or bring up the full demander+servers topology:
#   docker compose -f deploy/docker-compose.yml up --build
FROM python:3.11-slim

LABEL org.opencontainers.image.title="eventforge" \
      org.opencontainers.image.source="https://github.com/adnanhd/observer-pattern" \
      org.opencontainers.image.description="RPC server-worker node for eventforge-network topologies"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/work

# Install eventforge from the current source tree.
WORKDIR /opt/eventforge
COPY . /opt/eventforge
RUN pip install .

# Handler modules / demander scripts get mounted (or COPY'd) here.
WORKDIR /work

# The image *is* the worker entrypoint; args are the worker CLI flags.
# A demander container overrides this entrypoint to run a client script.
ENTRYPOINT ["python", "-m", "eventforge.worker"]
CMD ["--help"]
