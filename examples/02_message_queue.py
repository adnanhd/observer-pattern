"""MessageQueue - pub/sub messaging patterns.

Demonstrates:
- Publishing and subscribing to topics
- Request-reply pattern with RPC
"""

from callpyback import MessageQueue, RPCClient, RPCServer


def main():
    queue = MessageQueue()

    # Basic pub/sub
    print("=== Basic Pub/Sub ===")

    received = []

    @queue.on("events.user")
    def handle_user_event(msg):
        received.append(f"user: {msg.payload}")

    @queue.on("events.system")
    def handle_system_event(msg):
        received.append(f"system: {msg.payload}")

    queue.publish("events.user", {"action": "login", "user": "alice"})
    queue.publish("events.system", {"action": "startup"})

    print(f"Received: {received}")

    # Multiple subscribers to same topic
    print("\n=== Multiple Subscribers ===")

    log1, log2 = [], []

    @queue.on("notifications")
    def logger1(msg):
        log1.append(msg.payload)

    @queue.on("notifications")
    def logger2(msg):
        log2.append(f"[copy] {msg.payload}")

    queue.publish("notifications", "hello")
    queue.publish("notifications", "world")

    print(f"Logger 1: {log1}")
    print(f"Logger 2: {log2}")

    # RPC - request/reply
    print("\n=== RPC (Request/Reply) ===")

    rpc_server = RPCServer(queue, service_name="math")

    @rpc_server.register("add")
    def add(a: int, b: int) -> int:
        return a + b

    @rpc_server.register("multiply")
    def multiply(a: int, b: int) -> int:
        return a * b

    # Start server (non-blocking)
    rpc_server.serve(blocking=False)

    # Create client and call methods
    rpc_client = RPCClient(queue, service_name="math")

    result = rpc_client.call("add", a=5, b=3)
    print(f"5 + 3 = {result}")

    result = rpc_client.call("multiply", a=4, b=7)
    print(f"4 * 7 = {result}")

    rpc_server.stop()


if __name__ == "__main__":
    main()
