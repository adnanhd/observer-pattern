# Remote Queue

Bridge message queues across distributed nodes.

## Overview

`RemoteQueue` enables distributed messaging by:
- Connecting to remote node queues
- Subscribing to topics on remote nodes
- Publishing to remote nodes
- Broadcasting to all connected nodes

## Basic Usage

```python
from callpyback import MessageQueue, RemoteQueue

# Node 1
queue1 = MessageQueue()
remote1 = RemoteQueue(queue1, node_id="node-1")

# Node 2
queue2 = MessageQueue()
remote2 = RemoteQueue(queue2, node_id="node-2")

# Connect nodes (bidirectional)
remote1.connect("node-2", queue2)
remote2.connect("node-1", queue1)

# Subscribe to remote topic
@remote1.subscribe_remote("node-2", "events.order")
def handle_order(msg):
    print(f"Node-1 received: {msg.payload}")

# Publish from node-2
remote2.publish("events.order", {"id": 123, "status": "created"})
# Output: Node-1 received: {'id': 123, 'status': 'created'}
```

## Remote Subscriptions

Subscribe to topics on remote nodes:

```python
# Using decorator
@remote1.subscribe_remote("node-2", "events.*")
def handler(msg):
    print(f"Received: {msg.topic} -> {msg.payload}")

# Using method
def another_handler(msg):
    print(f"Another: {msg.payload}")

sub_id = remote1.add_remote_subscription("node-2", "users.created", another_handler)
```

## Remote Publishing

Publish directly to a specific node:

```python
# Publish to specific remote node
remote1.publish_remote("node-2", "commands.process", {"action": "start"})
```

## Broadcasting

Send messages to all connected nodes:

```python
# Broadcast to all nodes (including local)
message_ids = remote1.broadcast("system.shutdown", {"reason": "maintenance"})

# Returns dict: {"node-1": "msg-id-1", "node-2": "msg-id-2", ...}
print(message_ids)
```

## Local Queue Access

`RemoteQueue` also provides access to the local queue:

```python
remote = RemoteQueue(queue, node_id="node-1")

# Subscribe locally
@remote.on("local.events")
def local_handler(msg):
    print(msg.payload)

# Publish locally
remote.publish("local.events", {"data": "value"})

# Access underlying queue
local_queue = remote.local_queue
```

## Connection Management

```python
# Connect to remote
remote1.connect("node-2", queue2)

# Check node ID
print(remote1.node_id)  # "node-1"

# Disconnect
remote1.disconnect("node-2")

# Context manager for cleanup
with RemoteQueue(queue, node_id="node-1") as remote:
    remote.connect("node-2", queue2)
    # ...
# Automatically closes on exit
```

## API Reference

### RemoteQueue

```python
class RemoteQueue:
    def __init__(
        self,
        queue: MessageQueue,
        node_id: Optional[str] = None,  # Auto-generated if not provided
    ):
        """Create remote queue wrapper."""
    
    @property
    def node_id(self) -> str:
        """This node's identifier."""
    
    @property
    def local_queue(self) -> MessageQueue:
        """Underlying local queue."""
    
    def connect(self, remote_node_id: str, remote_queue: MessageQueue) -> None:
        """Connect to a remote node's queue."""
    
    def disconnect(self, remote_node_id: str) -> bool:
        """Disconnect from a remote node."""
    
    def subscribe_remote(
        self,
        remote_node_id: str,
        topic: str,
    ) -> Callable:
        """Decorator to subscribe to a topic on a remote node."""
    
    def add_remote_subscription(
        self,
        remote_node_id: str,
        topic: str,
        handler: Callable,
    ) -> str:
        """Subscribe to a topic on a remote node. Returns subscription ID."""
    
    def publish_remote(
        self,
        remote_node_id: str,
        topic: str,
        payload: Any,
        **headers,
    ) -> str:
        """Publish a message to a remote node. Returns message ID."""
    
    def publish(self, topic: str, payload: Any, **headers) -> str:
        """Publish to local queue."""
    
    def subscribe(self, topic: str, handler: Callable) -> str:
        """Subscribe to local queue."""
    
    def on(self, topic: str) -> Callable:
        """Decorator for local subscription."""
    
    def broadcast(self, topic: str, payload: Any, **headers) -> Dict[str, str]:
        """Broadcast to all connected nodes. Returns {node_id: message_id}."""
    
    def close(self) -> None:
        """Close all connections."""
```

### RemoteSubscription

```python
class RemoteSubscription:
    subscription_id: str
    topic: str
    remote_service: str
    handler: Callable
```

## Examples

### Distributed Event System

```python
from callpyback import MessageQueue, RemoteQueue

# Create nodes
nodes = {}
for name in ["gateway", "users", "orders", "notifications"]:
    queue = MessageQueue()
    nodes[name] = RemoteQueue(queue, node_id=name)

# Connect all nodes to gateway
for name, node in nodes.items():
    if name != "gateway":
        nodes["gateway"].connect(name, node.local_queue)
        node.connect("gateway", nodes["gateway"].local_queue)

# Users service subscribes to user events from gateway
@nodes["users"].subscribe_remote("gateway", "users.*")
def handle_user_event(msg):
    print(f"Users service: {msg.topic}")

# Orders service subscribes to order events
@nodes["orders"].subscribe_remote("gateway", "orders.*")
def handle_order_event(msg):
    print(f"Orders service: {msg.topic}")

# Notifications subscribes to all events
@nodes["notifications"].subscribe_remote("gateway", "*")
def handle_notification(msg):
    print(f"Notification: {msg.topic}")

# Gateway publishes events
nodes["gateway"].publish("users.created", {"id": 1, "name": "Alice"})
nodes["gateway"].publish("orders.placed", {"id": 100, "user_id": 1})
```

### Hub-and-Spoke Pattern

```python
from callpyback import MessageQueue, RemoteQueue

# Central hub
hub_queue = MessageQueue()
hub = RemoteQueue(hub_queue, node_id="hub")

# Spoke nodes
spokes = []
for i in range(3):
    spoke_queue = MessageQueue()
    spoke = RemoteQueue(spoke_queue, node_id=f"spoke-{i}")
    
    # Connect spoke to hub
    hub.connect(f"spoke-{i}", spoke_queue)
    spoke.connect("hub", hub_queue)
    
    # Each spoke handles commands
    @spoke.subscribe_remote("hub", "commands.*")
    def handle_command(msg, node=spoke):
        print(f"{node.node_id} received: {msg.payload}")
    
    spokes.append(spoke)

# Hub broadcasts command to all spokes
hub.broadcast("commands.execute", {"action": "sync"})
```

### Federated Services

```python
from callpyback import MessageQueue, RemoteQueue, RPCServer, RPCClient

# Region A
region_a_queue = MessageQueue()
region_a = RemoteQueue(region_a_queue, node_id="region-a")

region_a_rpc = RPCServer(region_a_queue, service_name="data")

@region_a_rpc.register()
def get_users():
    return [{"id": 1, "name": "Alice", "region": "A"}]

region_a_rpc.serve(blocking=False)

# Region B
region_b_queue = MessageQueue()
region_b = RemoteQueue(region_b_queue, node_id="region-b")

region_b_rpc = RPCServer(region_b_queue, service_name="data")

@region_b_rpc.register()
def get_users():
    return [{"id": 2, "name": "Bob", "region": "B"}]

region_b_rpc.serve(blocking=False)

# Connect regions
region_a.connect("region-b", region_b_queue)
region_b.connect("region-a", region_a_queue)

# Federated query from Region A
local_client = RPCClient(region_a_queue, service_name="data")
remote_client = RPCClient(region_b_queue, service_name="data")

all_users = local_client.get_users() + remote_client.get_users()
print(all_users)
# [{'id': 1, 'name': 'Alice', 'region': 'A'}, {'id': 2, 'name': 'Bob', 'region': 'B'}]
```
