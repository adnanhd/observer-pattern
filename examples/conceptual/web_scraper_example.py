#!/usr/bin/env python3
"""
Simple Web Scraper - Application Example
Demonstrates parallel web scraping with event-driven progress tracking.
"""

import random
import time
from typing import Dict

from callpyback import ExecutionMode, emit_event, on_event, execution_session


# Event handlers for progress tracking
@on_event("scrape.started")
def handle_scrape_started(message):
    url = message.payload.get("url", "unknown")
    print(f"🌐 Scraping started: {url}")


@on_event("scrape.completed")
def handle_scrape_completed(message):
    payload = message.payload
    url = payload.get("url", "unknown")
    size = payload.get("content_size", 0)
    print(f"✅ Scraped {url}: {size} chars")


@on_event("scrape.failed")
def handle_scrape_failed(message):
    url = message.payload.get("url", "unknown")
    error = message.payload.get("error", "Unknown error")
    print(f"❌ Failed {url}: {error}")


def scrape_url(url: str) -> Dict:
    """Simulate web scraping with random success/failure"""
    emit_event("scrape.started", {"url": url})

    # Simulate network delay
    time.sleep(random.uniform(0.1, 0.5))

    # Random failure (20% chance)
    if random.random() < 0.2:
        error = "Connection timeout"
        emit_event("scrape.failed", {"url": url, "error": error})
        raise ConnectionError(error)

    # Simulate scraped content
    content_size = random.randint(1000, 50000)
    title = f"Page Title {url.split('/')[-1]}"

    result = {
        "url": url,
        "title": title,
        "content_size": content_size,
        "links_found": random.randint(5, 25),
        "status": "success",
    }

    emit_event("scrape.completed", result)
    return result


def main():
    """Demo parallel web scraping with events"""
    print("🕷️  Simple Web Scraper with Execution Manager")
    print("=" * 50)

    # URLs to scrape
    urls = [
        "https://example.com/page1",
        "https://example.com/page2",
        "https://news.site/article1",
        "https://blog.com/post1",
        "https://shop.com/product1",
        "https://forum.net/thread1",
        "https://wiki.org/topic1",
        "https://docs.site/guide1",
    ]

    with execution_session() as manager:
        # Configure for I/O intensive work (web requests)
        manager.configure().max_threads(4).execution_mode(ExecutionMode.THREAD).apply()

        print(f"📡 Scraping {len(urls)} URLs in parallel...")

        # Scrape all URLs in parallel
        results = manager.map_parallel(scrape_url, urls)

        # Process results
        successful = [
            r for r in results if isinstance(r, dict) and r.get("status") == "success"
        ]
        failed = len(results) - len(successful)

        total_content = sum(r.get("content_size", 0) for r in successful)
        total_links = sum(r.get("links_found", 0) for r in successful)

        print(f"\n📊 Scraping Results:")
        print(f"  ✅ Successful: {len(successful)}")
        print(f"  ❌ Failed: {failed}")
        print(f"  📄 Total content: {total_content:,} characters")
        print(f"  🔗 Total links found: {total_links}")

        # Show performance metrics
        metrics = manager.get_metrics()
        print(f"\n📈 Performance:")
        print(f"  Tasks completed: {metrics['tasks_completed']}")
        print(f"  Events published: {metrics['events_published']}")


if __name__ == "__main__":
    main()
