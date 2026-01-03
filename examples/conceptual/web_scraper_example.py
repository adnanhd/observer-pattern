#!/usr/bin/env python3
"""
Web Scraper - Conceptual Example
Demonstrates async-like processing with message queue for web scraping simulation.
"""

import random
import time
from dataclasses import dataclass
from typing import List, Optional

from callpyback import (
    ExecutionMode,
    Executor,
    MessageQueue,
    MetricsObserver,
    TimingObserver,
    observe,
)


@dataclass
class ScrapeResult:
    url: str
    status: str
    content_length: int = 0
    error: Optional[str] = None
    duration: float = 0.0


def simulate_fetch(url: str) -> ScrapeResult:
    """Simulate fetching a URL."""
    start = time.perf_counter()

    # Simulate network latency
    time.sleep(random.uniform(0.05, 0.15))

    # Simulate occasional failures
    if random.random() < 0.1:
        return ScrapeResult(
            url=url,
            status="error",
            error="Connection timeout",
            duration=time.perf_counter() - start,
        )

    # Simulate successful fetch
    content_length = random.randint(1000, 50000)
    return ScrapeResult(
        url=url,
        status="success",
        content_length=content_length,
        duration=time.perf_counter() - start,
    )


def main():
    queue = MessageQueue()
    timing = TimingObserver()
    metrics = MetricsObserver()

    results: List[ScrapeResult] = []
    total_bytes = 0

    # Event handlers
    @queue.on("scrape.started")
    def on_start(msg):
        print(f"Starting scrape: {msg.payload['url']}")

    @queue.on("scrape.complete")
    def on_complete(msg):
        result = msg.payload
        results.append(
            ScrapeResult(
                url=result["url"],
                status=result["status"],
                content_length=result.get("content_length", 0),
                error=result.get("error"),
                duration=result.get("duration", 0),
            )
        )
        if result["status"] == "success":
            nonlocal total_bytes
            total_bytes += result.get("content_length", 0)

    @queue.on("scrape.batch_complete")
    def on_batch_complete(msg):
        stats = msg.payload
        print(f"\nBatch complete:")
        print(f"  Total URLs: {stats['total']}")
        print(f"  Success: {stats['success']}")
        print(f"  Failed: {stats['failed']}")
        print(f"  Total bytes: {stats['total_bytes']:,}")
        print(f"  Total time: {stats['total_time']:.2f}s")

    # Scrape function with observers
    @observe(timing, metrics)
    def scrape_url(url: str) -> dict:
        queue.publish("scrape.started", {"url": url})
        result = simulate_fetch(url)
        queue.publish("scrape.complete", result.__dict__)
        return result.__dict__

    # URLs to scrape
    urls = [
        "https://example.com/page1",
        "https://example.com/page2",
        "https://example.com/page3",
        "https://example.com/page4",
        "https://example.com/page5",
        "https://example.com/page6",
        "https://example.com/page7",
        "https://example.com/page8",
    ]

    print("=== Starting Web Scraper ===\n")
    start_time = time.perf_counter()

    # Scrape with thread pool for parallel I/O
    with Executor(mode=ExecutionMode.THREAD, max_workers=4) as executor:
        task_ids = [executor.submit(scrape_url, url) for url in urls]

        # Wait for all to complete
        for tid in task_ids:
            executor.result(tid)

    total_time = time.perf_counter() - start_time

    # Publish batch completion
    success_count = sum(1 for r in results if r.status == "success")
    queue.publish(
        "scrape.batch_complete",
        {
            "total": len(urls),
            "success": success_count,
            "failed": len(urls) - success_count,
            "total_bytes": total_bytes,
            "total_time": total_time,
        },
    )

    time.sleep(0.1)  # Allow handlers to process

    print(f"\n=== Stats ===")
    print(
        f"Timing: avg={timing.stats['avg'] * 1000:.1f}ms, max={timing.stats['max'] * 1000:.1f}ms"
    )
    print(f"Metrics: {metrics.stats}")


if __name__ == "__main__":
    main()
