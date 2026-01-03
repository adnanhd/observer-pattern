#!/usr/bin/env python3
"""
Messaging Patterns - Conceptual Example
Demonstrates pub-sub and request-reply messaging patterns.
"""

import threading
import time

from callpyback import Executor, MessageQueue, RPCClient, RPCServer


def main():
    queue = MessageQueue()

    print("=== Pub-Sub Pattern ===")

    # Multiple subscribers to same topic
    received_by = {"handler1": [], "handler2": []}

    @queue.on("news.tech")
    def tech_handler_1(msg):
        received_by["handler1"].append(msg.payload)
        print(f"Handler 1 received: {msg.payload['title']}")

    @queue.on("news.tech")
    def tech_handler_2(msg):
        received_by["handler2"].append(msg.payload)
        print(f"Handler 2 received: {msg.payload['title']}")

    queue.publish(
        "news.tech", {"title": "New Python Release", "category": "programming"}
    )
    queue.publish("news.tech", {"title": "New Python Release", "category": "programming"})
    queue.publish("news.tech", {"title": "AI Breakthrough", "category": "ml"})

    time.sleep(0.1)

    print(f"\nHandler 1 received {len(received_by['handler1'])} messages")
    print(f"Handler 2 received {len(received_by['handler2'])} messages")

    print("\n=== Request-Reply Pattern (RPC) ===")

    executor = Executor()
    server = RPCServer(queue, executor, service_name="calculator")

    @server.register()
    def add(a: int, b: int) -> int:
        return a + b

    @server.register()
    def multiply(a: int, b: int) -> int:
        return a * b

    @server.register()
    def factorial(n: int) -> int:
        if n <= 1:
            return 1
        result = 1
        for i in range(2, n + 1):
            result *= i
        return result

    # Start server in background
    server.serve(blocking=False)
    time.sleep(0.1)

    # Create client
    client = RPCClient(queue, service_name="calculator", timeout=5.0)

    # Make RPC calls
    print(f"add(5, 3) = {client.call('add', 5, 3)}")
    print(f"multiply(4, 7) = {client.call('multiply', 4, 7)}")
    print(f"factorial(5) = {client.call('factorial', 5)}")

    # Dynamic method access
    print(f"client.add(10, 20) = {client.add(10, 20)}")

    server.stop()

    print("\n=== Fan-Out Pattern ===")

    results = []

    @queue.on("task.result")
    def collect_results(msg):
        results.append(msg.payload)

    # Simulate fan-out: one message triggers multiple handlers
    @queue.on("job.start")
    def worker_1(msg):
        time.sleep(0.01)
        queue.publish("task.result", {"worker": 1, "job_id": msg.payload["id"]})

    @queue.on("job.start")
    def worker_2(msg):
        time.sleep(0.01)
        queue.publish("task.result", {"worker": 2, "job_id": msg.payload["id"]})

    queue.publish("job.start", {"id": "JOB-001"})

    time.sleep(0.1)
    print(f"Collected {len(results)} results from workers")

    print("\nDone!")


if __name__ == "__main__":
    main()
