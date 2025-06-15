#!/usr/bin/env python3
"""
Uses existing CallPyBack plugins: ThreadExecutor, EventBus
"""

import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from callpyback import CallPyBack, on_call, on_failure, on_success
from callpyback.observers.base import BaseObserver
from callpyback.plugins.core.message_queue import EventBus
from callpyback.plugins.executors.thread_executor import ThreadExecutor


class QueryType(Enum):
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


@dataclass
class DatabaseQuery:
    query_id: str
    query_type: QueryType
    table: str
    sql: str
    params: Optional[Dict] = None
    timeout: float = 30.0


class DatabaseObserver(BaseObserver):
    """Database operations monitoring"""

    def __init__(self):
        super().__init__(priority=90, name="DatabaseOps")
        self.query_stats = {
            "SELECT": {"count": 0, "total_time": 0.0},
            "INSERT": {"count": 0, "total_time": 0.0},
            "UPDATE": {"count": 0, "total_time": 0.0},
            "DELETE": {"count": 0, "total_time": 0.0},
        }
        self.errors = 0
        self.connections_active = 0

    def update(self, context):
        if context.state.name == "STARTED":
            self.connections_active += 1
        elif context.state.name == "COMPLETED":
            self.connections_active -= 1

            if context.result and context.result.value:
                result = context.result.value
                if "query_type" in result and "execution_time" in result:
                    query_type = result["query_type"]
                    exec_time = result["execution_time"]

                    if query_type in self.query_stats:
                        self.query_stats[query_type]["count"] += 1
                        self.query_stats[query_type]["total_time"] += exec_time
        elif context.state.name == "FAILED":
            self.connections_active -= 1
            self.errors += 1


# Global instances
db_observer = DatabaseObserver()
event_bus = EventBus()
thread_executor = ThreadExecutor(max_workers=5)


def mock_database_connection():
    """Mock database connection with realistic delays"""
    # Simulate connection time
    time.sleep(random.uniform(0.01, 0.05))

    return {
        "connection_id": f"conn_{random.randint(1000, 9999)}",
        "host": "localhost",
        "database": "test_db",
        "connected_at": time.time(),
    }


@CallPyBack(
    observers=[
        db_observer,
        on_call(
            lambda context: print(
                f"🔍 Executing {context.arguments['query'].query_type.value} on {context.arguments['query'].table}"
            )
        ),
        on_success(
            lambda result: event_bus.publish("db.query.completed", result.value)
        ),
        on_failure(
            lambda result: event_bus.publish(
                "db.query.failed", {"error": str(result.exception)}
            )
        ),
    ]
)
def execute_database_query(query: DatabaseQuery) -> Dict[str, Any]:
    """Execute database query with monitoring"""

    start_time = time.time()

    # Simulate connection
    connection = mock_database_connection()

    try:
        # Simulate query execution time based on type
        execution_times = {
            QueryType.SELECT: (0.1, 0.5),
            QueryType.INSERT: (0.05, 0.2),
            QueryType.UPDATE: (0.1, 0.3),
            QueryType.DELETE: (0.05, 0.25),
        }

        min_time, max_time = execution_times.get(query.query_type, (0.1, 0.3))
        time.sleep(random.uniform(min_time, max_time))

        # Simulate occasional failures
        if random.random() < 0.05:  # 5% failure rate
            raise RuntimeError("Database error: Connection timeout")

        # Generate mock results
        if query.query_type == QueryType.SELECT:
            row_count = random.randint(0, 100)
            result_data = [{"id": i, "value": f"data_{i}"} for i in range(row_count)]
        else:
            result_data = {"affected_rows": random.randint(1, 10)}

        execution_time = time.time() - start_time

        return {
            "query_id": query.query_id,
            "query_type": query.query_type.value,
            "table": query.table,
            "execution_time": execution_time,
            "connection_id": connection["connection_id"],
            "result": result_data,
            "status": "success",
        }

    except Exception as e:
        execution_time = time.time() - start_time
        return {
            "query_id": query.query_id,
            "query_type": query.query_type.value,
            "table": query.table,
            "execution_time": execution_time,
            "error": str(e),
            "status": "failed",
        }


@CallPyBack(
    observers=[
        on_call(
            lambda context: print(
                f"📦 Starting transaction with {len(context.arguments['queries'])} queries"
            )
        ),
        on_success(
            lambda result: event_bus.publish("db.transaction.completed", result.value)
        ),
        on_failure(
            lambda result: event_bus.publish(
                "db.transaction.failed", {"error": str(result.exception)}
            )
        ),
    ]
)
def execute_transaction(queries: List[DatabaseQuery]) -> Dict[str, Any]:
    """Execute database transaction"""

    start_time = time.time()
    transaction_id = f"txn_{int(time.time() * 1000) % 10000}"

    try:
        # Simulate transaction setup
        time.sleep(random.uniform(0.01, 0.03))

        results = []
        for query in queries:
            result = execute_database_query(query)
            results.append(result)

            # If any query fails, rollback transaction
            if result["status"] == "failed":
                raise RuntimeError(
                    f"Transaction rollback: Query {query.query_id} failed"
                )

        # Simulate commit
        time.sleep(random.uniform(0.01, 0.02))

        return {
            "transaction_id": transaction_id,
            "queries_executed": len(queries),
            "execution_time": time.time() - start_time,
            "results": results,
            "status": "committed",
        }

    except Exception as e:
        return {
            "transaction_id": transaction_id,
            "execution_time": time.time() - start_time,
            "error": str(e),
            "status": "rolled_back",
        }


class SimpleDatabaseManager:
    """Simplified database manager using CallPyBack plugins"""

    def __init__(self):
        self.event_bus = event_bus
        self.executor = thread_executor
        self.observer = db_observer

        # Start services
        self.executor.start()

        # Setup event handlers
        self.event_bus.subscribe("db.query.completed", self._on_query_completed)
        self.event_bus.subscribe("db.query.failed", self._on_query_failed)
        self.event_bus.subscribe(
            "db.transaction.completed", self._on_transaction_completed
        )

    def _on_query_completed(self, message):
        """Handle query completion"""
        payload = message.payload
        query_type = payload.get("query_type", "unknown")
        table = payload.get("table", "unknown")
        exec_time = payload.get("execution_time", 0)
        print(f"✅ {query_type} on {table}: {exec_time:.3f}s")

    def _on_query_failed(self, message):
        """Handle query failure"""
        error = message.payload.get("error", "Unknown error")
        print(f"❌ Query failed: {error}")

    def _on_transaction_completed(self, message):
        """Handle transaction completion"""
        payload = message.payload
        txn_id = payload.get("transaction_id", "unknown")
        queries = payload.get("queries_executed", 0)
        print(f"✅ Transaction {txn_id}: {queries} queries committed")

    def create_sample_queries(self, count: int = 20) -> List[DatabaseQuery]:
        """Create sample database queries"""
        queries = []
        tables = ["users", "orders", "products", "sessions"]

        for i in range(count):
            table = random.choice(tables)
            query_type = random.choice(list(QueryType))

            query = DatabaseQuery(
                query_id=f"query_{i:03d}",
                query_type=query_type,
                table=table,
                sql=f"{query_type.value} FROM {table} WHERE id = ?",
                params={"id": random.randint(1, 1000)},
            )
            queries.append(query)

        return queries

    def execute_queries_parallel(
        self, queries: List[DatabaseQuery]
    ) -> List[Dict[str, Any]]:
        """Execute queries in parallel using thread executor"""

        print(f"🚀 Executing {len(queries)} queries in parallel")

        # Submit tasks
        task_ids = []
        for query in queries:
            task_id = self.executor.submit(
                execute_database_query,
                query,
                priority=1 if query.query_type == QueryType.SELECT else 2,
            )
            task_ids.append(task_id)

        # Collect results
        results = []
        for task_id in task_ids:
            try:
                result = self.executor.get_result(task_id, timeout=30)
                results.append(result.result)
            except Exception as e:
                results.append({"error": str(e), "status": "timeout"})

        return results

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get database performance metrics"""
        stats = {}
        for query_type, data in self.observer.query_stats.items():
            if data["count"] > 0:
                avg_time = data["total_time"] / data["count"]
                stats[query_type] = {
                    "count": data["count"],
                    "total_time": data["total_time"],
                    "avg_time": avg_time,
                }

        return {
            "query_statistics": stats,
            "active_connections": self.observer.connections_active,
            "total_errors": self.observer.errors,
            "executor_stats": self.executor.get_stats(),
        }

    def shutdown(self):
        """Clean shutdown"""
        self.executor.stop()


if __name__ == "__main__":
    """Demo the simplified database manager"""
    db_manager = SimpleDatabaseManager()

    try:
        # Create sample queries
        queries = db_manager.create_sample_queries(15)
        print(f"📋 Created {len(queries)} sample queries")

        # Execute individual queries
        individual_results = db_manager.execute_queries_parallel(queries[:10])

        # Execute transaction
        transaction_queries = queries[10:13]
        transaction_result = execute_transaction(transaction_queries)

        # Show results
        successful_individual = sum(
            1 for r in individual_results if r.get("status") == "success"
        )
        print(
            f"\n📊 Individual queries: {successful_individual}/{len(individual_results)} successful"
        )
        print(f"📦 Transaction: {transaction_result['status']}")

        # Show performance metrics
        metrics = db_manager.get_performance_metrics()
        print("\n📈 Performance Metrics:")
        for query_type, stats in metrics["query_statistics"].items():
            print(
                f"  {query_type}: {stats['count']} queries, {stats['avg_time']:.3f}s avg"
            )
        print(f"  Errors: {metrics['total_errors']}")

    finally:
        db_manager.shutdown()
