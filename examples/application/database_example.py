#!/usr/bin/env python3
"""
Database Operations Monitoring Example
Demonstrates monitoring database operations with CallPyBack for:
- Query performance tracking
- Connection pool monitoring
- Slow query detection
- Database error pattern analysis
- Transaction monitoring
"""

import random
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from callpyback import (
    CallPyBack,
    DefaultErrorHandler,
    ExecutionContext,
    ExecutionState,
    on_call,
    on_completion,
    on_failure,
    on_success,
)
from callpyback.observers.base import BaseObserver


class QueryType(Enum):
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    TRANSACTION = "TRANSACTION"


@dataclass
class DatabaseConnection:
    connection_id: str
    created_at: float
    last_used: float
    is_active: bool = True
    query_count: int = 0


@dataclass
class QueryInfo:
    query_id: str
    query_type: QueryType
    table: str
    sql: str
    params: Dict[str, Any] = None
    connection_id: str = None


class DatabaseObserver(BaseObserver):
    """Monitor database operations and performance"""

    def __init__(self):
        super().__init__(priority=90, name="DatabaseMonitor")
        self.query_stats = defaultdict(
            lambda: {"count": 0, "total_time": 0, "errors": 0, "slow_queries": 0}
        )
        self.slow_query_threshold = 0.5  # 500ms
        self.slow_queries_log = deque(maxlen=100)
        self.error_patterns = defaultdict(int)
        self.table_access_patterns = defaultdict(lambda: defaultdict(int))
        self.lock = threading.Lock()

    def update(self, context: ExecutionContext) -> None:
        if context.state != ExecutionState.COMPLETED:
            return

        query_info = context.arguments.get("query_info")
        if not query_info:
            return

        with self.lock:
            query_type = query_info.query_type.value
            table = query_info.table

            # Update query statistics
            stats = self.query_stats[query_type]
            stats["count"] += 1

            # Track table access patterns
            self.table_access_patterns[table][query_type] += 1

            if context.result:
                execution_time = getattr(context.result, "execution_time", 0)
                stats["total_time"] += execution_time

                # Detect slow queries
                if execution_time > self.slow_query_threshold:
                    stats["slow_queries"] += 1
                    self.slow_queries_log.append(
                        {
                            "timestamp": context.timestamp,
                            "query_id": query_info.query_id,
                            "query_type": query_type,
                            "table": table,
                            "execution_time": execution_time,
                            "sql": (
                                query_info.sql[:100] + "..."
                                if len(query_info.sql) > 100
                                else query_info.sql
                            ),
                            "connection_id": query_info.connection_id,
                        }
                    )
                    print(
                        f"🐌 Slow query detected: {query_type} on {table} ({execution_time:.3f}s)"
                    )

                # Track errors
                if not context.is_successful:
                    stats["errors"] += 1
                    error_msg = str(
                        getattr(context.result, "exception", "Unknown error")
                    )
                    error_pattern = f"{query_type}:{error_msg.split(':')[0] if ':' in error_msg else error_msg[:50]}"
                    self.error_patterns[error_pattern] += 1

    def get_query_performance_report(self):
        """Generate query performance report"""
        with self.lock:
            report = {}
            for query_type, stats in self.query_stats.items():
                avg_time = (
                    stats["total_time"] / stats["count"] if stats["count"] > 0 else 0
                )
                error_rate = (
                    (stats["errors"] / stats["count"]) * 100
                    if stats["count"] > 0
                    else 0
                )
                slow_rate = (
                    (stats["slow_queries"] / stats["count"]) * 100
                    if stats["count"] > 0
                    else 0
                )

                report[query_type] = {
                    "total_queries": stats["count"],
                    "avg_execution_time": f"{avg_time:.3f}s",
                    "error_rate": f"{error_rate:.1f}%",
                    "slow_query_rate": f"{slow_rate:.1f}%",
                    "total_execution_time": f"{stats['total_time']:.3f}s",
                }
            return report

    def get_table_access_report(self):
        """Analyze table access patterns"""
        with self.lock:
            return {
                table: dict(operations)
                for table, operations in self.table_access_patterns.items()
            }

    def get_slow_queries(self, limit: int = 10):
        """Get recent slow queries"""
        with self.lock:
            return list(self.slow_queries_log)[-limit:]

    def get_error_analysis(self):
        """Get error pattern analysis"""
        with self.lock:
            return dict(self.error_patterns)


class ConnectionPoolObserver(BaseObserver):
    """Monitor database connection pool"""

    def __init__(self, max_connections: int = 10):
        super().__init__(priority=85, name="ConnectionPool")
        self.max_connections = max_connections
        self.active_connections = {}
        self.connection_history = deque(maxlen=1000)
        self.pool_stats = {
            "connections_created": 0,
            "connections_closed": 0,
            "pool_exhausted_events": 0,
            "peak_usage": 0,
        }
        self.lock = threading.Lock()

    def update(self, context: ExecutionContext) -> None:
        with self.lock:
            if context.state == ExecutionState.PRE_EXECUTION:
                # Track connection usage
                query_info = context.arguments.get("query_info")
                if query_info and query_info.connection_id:
                    connection_id = query_info.connection_id

                    if connection_id not in self.active_connections:
                        # New connection
                        self.active_connections[connection_id] = DatabaseConnection(
                            connection_id=connection_id,
                            created_at=time.time(),
                            last_used=time.time(),
                        )
                        self.pool_stats["connections_created"] += 1
                    else:
                        # Update existing connection
                        self.active_connections[connection_id].last_used = time.time()
                        self.active_connections[connection_id].query_count += 1

                    # Track peak usage
                    current_usage = len(self.active_connections)
                    if current_usage > self.pool_stats["peak_usage"]:
                        self.pool_stats["peak_usage"] = current_usage

                    # Check for pool exhaustion
                    if current_usage >= self.max_connections:
                        self.pool_stats["pool_exhausted_events"] += 1
                        print(
                            f"⚠️  Connection pool exhausted! {current_usage}/{self.max_connections} connections in use"
                        )

                    self.connection_history.append(
                        {
                            "timestamp": context.timestamp,
                            "connection_id": connection_id,
                            "action": "query_start",
                            "active_connections": current_usage,
                        }
                    )

    def cleanup_old_connections(self, max_idle_time: float = 300):
        """Cleanup connections idle for more than max_idle_time seconds"""
        with self.lock:
            current_time = time.time()
            to_remove = []

            for conn_id, conn in self.active_connections.items():
                if current_time - conn.last_used > max_idle_time:
                    to_remove.append(conn_id)

            for conn_id in to_remove:
                del self.active_connections[conn_id]
                self.pool_stats["connections_closed"] += 1
                print(f"🔌 Closed idle connection: {conn_id}")

    def get_pool_status(self):
        """Get current pool status"""
        with self.lock:
            active_count = len(self.active_connections)
            return {
                "active_connections": active_count,
                "available_connections": self.max_connections - active_count,
                "utilization": f"{(active_count / self.max_connections) * 100:.1f}%",
                "peak_usage": self.pool_stats["peak_usage"],
                "total_created": self.pool_stats["connections_created"],
                "total_closed": self.pool_stats["connections_closed"],
                "pool_exhausted_events": self.pool_stats["pool_exhausted_events"],
            }

    def get_connection_details(self):
        """Get details of active connections"""
        with self.lock:
            current_time = time.time()
            details = {}
            for conn_id, conn in self.active_connections.items():
                idle_time = current_time - conn.last_used
                details[conn_id] = {
                    "query_count": conn.query_count,
                    "idle_time": f"{idle_time:.1f}s",
                    "age": f"{current_time - conn.created_at:.1f}s",
                }
            return details


# Set up monitoring
db_monitor = DatabaseObserver()
connection_pool_monitor = ConnectionPoolObserver(max_connections=5)

# Error handler for database operations
db_error_handler = DefaultErrorHandler(
    default_return={"error": "Database operation failed", "rows_affected": 0}
)


class MockDatabase:
    """Mock database for simulation"""

    def __init__(self):
        self.tables = {
            "users": [
                {"id": i, "name": f"User {i}", "email": f"user{i}@example.com"}
                for i in range(1, 101)
            ],
            "orders": [
                {
                    "id": i,
                    "user_id": random.randint(1, 100),
                    "amount": random.randint(10, 1000),
                }
                for i in range(1, 201)
            ],
            "products": [
                {"id": i, "name": f"Product {i}", "price": random.randint(5, 500)}
                for i in range(1, 51)
            ],
        }
        self.connection_counter = 0
        self.lock = threading.Lock()

    def get_connection(self):
        """Simulate getting a database connection"""
        with self.lock:
            self.connection_counter += 1
            return f"conn_{self.connection_counter}_{threading.current_thread().name}"

    def execute_query(self, query_info: QueryInfo):
        """Simulate query execution"""

        # Simulate network/disk latency
        base_latency = random.uniform(0.01, 0.1)

        # Different query types have different performance characteristics
        if query_info.query_type == QueryType.SELECT:
            # SELECT queries vary by complexity
            if "JOIN" in query_info.sql.upper():
                latency = base_latency + random.uniform(
                    0.1, 0.8
                )  # Complex joins are slower
            else:
                latency = base_latency + random.uniform(0.01, 0.2)
        elif query_info.query_type == QueryType.INSERT:
            latency = base_latency + random.uniform(0.02, 0.15)
        elif query_info.query_type == QueryType.UPDATE:
            latency = base_latency + random.uniform(0.05, 0.3)
        elif query_info.query_type == QueryType.DELETE:
            latency = base_latency + random.uniform(0.03, 0.2)
        else:
            latency = base_latency

        time.sleep(latency)

        # Simulate occasional database errors
        if random.random() < 0.08:  # 8% error rate
            error_types = [
                "Connection timeout",
                "Deadlock detected",
                "Table lock timeout",
                "Constraint violation",
                "Invalid syntax",
            ]
            raise RuntimeError(f"Database error: {random.choice(error_types)}")

        # Return mock results
        if query_info.query_type == QueryType.SELECT:
            table_data = self.tables.get(query_info.table, [])
            return {
                "rows": table_data[: random.randint(1, 10)],
                "count": len(table_data),
            }
        else:
            return {"rows_affected": random.randint(1, 5)}


# Mock database instance
mock_db = MockDatabase()


@CallPyBack(
    observers=[
        db_monitor,
        connection_pool_monitor,
        on_call(
            lambda context: print(
                f"🗃️  Executing: {context.arguments['query_info'].query_type.value} on {context.arguments['query_info'].table}"
            )
        ),
        on_failure(lambda result: print(f"❌ Database error: {result.exception}")),
    ],
    error_handler=db_error_handler,
    exception_classes=(RuntimeError, ConnectionError, TimeoutError),
)
def execute_database_query(query_info: QueryInfo) -> Dict[str, Any]:
    """Execute a database query with monitoring"""

    # Get database connection
    connection_id = mock_db.get_connection()
    query_info.connection_id = connection_id

    # Execute the query
    result = mock_db.execute_query(query_info)

    return {
        "query_id": query_info.query_id,
        "connection_id": connection_id,
        "result": result,
    }


@CallPyBack(
    observers=[db_monitor], variable_names=["transaction_state", "queries_executed"]
)
def execute_transaction(queries: List[QueryInfo]) -> Dict[str, Any]:
    """Execute multiple queries as a transaction"""

    transaction_state = "started"
    queries_executed = 0
    results = []

    try:
        connection_id = mock_db.get_connection()

        transaction_state = "executing"

        for query in queries:
            query.connection_id = connection_id
            result = execute_database_query(query)
            results.append(result)
            queries_executed += 1

        transaction_state = "committed"

        return {
            "transaction_id": f"txn_{connection_id}_{time.time()}",
            "queries_executed": queries_executed,
            "results": results,
            "status": "committed",
        }

    except Exception as e:
        transaction_state = "rolled_back"
        raise RuntimeError(f"Transaction failed after {queries_executed} queries: {e}")


def create_sample_queries() -> List[QueryInfo]:
    """Create sample database queries for testing"""

    queries = []

    # SELECT queries
    select_queries = [
        ("users", "SELECT * FROM users WHERE id = %(user_id)s"),
        ("orders", "SELECT * FROM orders WHERE user_id = %(user_id)s"),
        ("products", "SELECT * FROM products WHERE price > %(min_price)s"),
        ("orders", "SELECT o.*, u.name FROM orders o JOIN users u ON o.user_id = u.id"),
        ("users", "SELECT COUNT(*) FROM users WHERE email LIKE %(pattern)s"),
    ]

    for i, (table, sql) in enumerate(select_queries * 10):  # 50 SELECT queries
        queries.append(
            QueryInfo(
                query_id=f"select_{i:03d}",
                query_type=QueryType.SELECT,
                table=table,
                sql=sql,
                params={
                    "user_id": random.randint(1, 100),
                    "min_price": random.randint(10, 100),
                    "pattern": "user%",
                },
            )
        )

    # INSERT queries
    for i in range(15):
        table = random.choice(["users", "orders", "products"])
        queries.append(
            QueryInfo(
                query_id=f"insert_{i:03d}",
                query_type=QueryType.INSERT,
                table=table,
                sql=f"INSERT INTO {table} VALUES (...)",
                params={"data": f"new_data_{i}"},
            )
        )

    # UPDATE queries
    for i in range(10):
        table = random.choice(["users", "orders", "products"])
        queries.append(
            QueryInfo(
                query_id=f"update_{i:03d}",
                query_type=QueryType.UPDATE,
                table=table,
                sql=f"UPDATE {table} SET ... WHERE id = %(id)s",
                params={"id": random.randint(1, 100)},
            )
        )

    # DELETE queries
    for i in range(5):
        table = random.choice(["users", "orders"])
        queries.append(
            QueryInfo(
                query_id=f"delete_{i:03d}",
                query_type=QueryType.DELETE,
                table=table,
                sql=f"DELETE FROM {table} WHERE id = %(id)s",
                params={"id": random.randint(1, 100)},
            )
        )

    return queries


def simulate_database_workload():
    """Simulate realistic database workload"""

    print("🚀 Starting Database Operations Simulation")
    print("=" * 50)

    # Create sample queries
    queries = create_sample_queries()
    random.shuffle(queries)

    print(f"📋 Generated {len(queries)} database queries")

    # Execute queries with some concurrency
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = []
    failed_queries = 0

    # Execute some individual queries
    print("\n🔄 Executing individual queries...")
    for i, query in enumerate(queries[:60]):  # Execute 60 individual queries
        try:
            result = execute_database_query(query)
            results.append(result)
            if i % 10 == 0:
                print(f"  Processed {i+1}/60 queries...")
        except Exception as e:
            failed_queries += 1
            print(f"  Query {query.query_id} failed: {e}")

        # Small delay between queries
        time.sleep(random.uniform(0.01, 0.05))

    # Execute some transactions
    print(f"\n📦 Executing transactions...")
    remaining_queries = queries[60:]

    # Group remaining queries into transactions
    transaction_size = 3
    for i in range(0, len(remaining_queries), transaction_size):
        transaction_queries = remaining_queries[i : i + transaction_size]

        try:
            transaction_result = execute_transaction(transaction_queries)
            results.append(transaction_result)
            print(
                f"  Transaction {i//transaction_size + 1} completed with {len(transaction_queries)} queries"
            )
        except Exception as e:
            failed_queries += len(transaction_queries)
            print(f"  Transaction {i//transaction_size + 1} failed: {e}")

    # Concurrent query execution
    print(f"\n⚡ Executing concurrent queries...")
    concurrent_queries = create_sample_queries()[:30]  # 30 more queries

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="DBWorker") as executor:
        futures = []
        for query in concurrent_queries:
            future = executor.submit(execute_database_query, query)
            futures.append(future)

        for future in as_completed(futures, timeout=30):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                failed_queries += 1

    # Cleanup old connections
    connection_pool_monitor.cleanup_old_connections(max_idle_time=1)

    print(f"\n🏁 Database workload completed")
    print(f"   Total operations: {len(results) + failed_queries}")
    print(f"   Successful: {len(results)}")
    print(f"   Failed: {failed_queries}")

    # Generate comprehensive database analysis
    print("\n" + "=" * 60)
    print("📊 DATABASE PERFORMANCE ANALYSIS")
    print("=" * 60)

    # Query performance report
    query_report = db_monitor.get_query_performance_report()
    print(f"\n🔍 Query Performance by Type:")
    for query_type, stats in query_report.items():
        print(f"  {query_type}:")
        print(f"    Total Queries: {stats['total_queries']}")
        print(f"    Avg Time: {stats['avg_execution_time']}")
        print(f"    Error Rate: {stats['error_rate']}")
        print(f"    Slow Query Rate: {stats['slow_query_rate']}")

    # Table access patterns
    table_report = db_monitor.get_table_access_report()
    print(f"\n📊 Table Access Patterns:")
    for table, operations in table_report.items():
        total_ops = sum(operations.values())
        print(f"  {table} ({total_ops} operations):")
        for op_type, count in operations.items():
            percentage = (count / total_ops) * 100
            print(f"    {op_type}: {count} ({percentage:.1f}%)")

    # Slow queries
    slow_queries = db_monitor.get_slow_queries(limit=5)
    if slow_queries:
        print(f"\n🐌 Recent Slow Queries:")
        for slow_query in slow_queries:
            print(
                f"  {slow_query['query_type']} on {slow_query['table']}: {slow_query['execution_time']:.3f}s"
            )
            print(f"    SQL: {slow_query['sql']}")

    # Connection pool status
    pool_status = connection_pool_monitor.get_pool_status()
    print(f"\n🔌 Connection Pool Status:")
    print(f"  Active Connections: {pool_status['active_connections']}")
    print(f"  Available: {pool_status['available_connections']}")
    print(f"  Utilization: {pool_status['utilization']}")
    print(f"  Peak Usage: {pool_status['peak_usage']}")
    print(f"  Total Created: {pool_status['total_created']}")
    print(f"  Pool Exhausted Events: {pool_status['pool_exhausted_events']}")

    # Connection details
    connection_details = connection_pool_monitor.get_connection_details()
    if connection_details:
        print(f"\n🔗 Active Connection Details:")
        for conn_id, details in list(connection_details.items())[:5]:  # Show first 5
            print(f"  {conn_id}:")
            print(f"    Queries: {details['query_count']}")
            print(f"    Idle: {details['idle_time']}")
            print(f"    Age: {details['age']}")

    # Error analysis
    error_analysis = db_monitor.get_error_analysis()
    if error_analysis:
        print(f"\n❌ Error Pattern Analysis:")
        for pattern, count in error_analysis.items():
            print(f"  {pattern}: {count} occurrences")


if __name__ == "__main__":
    simulate_database_workload()
