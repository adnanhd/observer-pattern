#!/usr/bin/env python3
"""
Custom Observers Example
Demonstrates building domain-specific observers for specialized monitoring.
"""

import random
import time
from collections import defaultdict

from callpyback import CallPyBack
from callpyback.core.state_machine import ExecutionState
from callpyback.observers.base import BaseObserver


class FinancialAuditObserver(BaseObserver):
    """Custom observer for financial transaction auditing."""

    def __init__(self):
        super().__init__(priority=95, name="FinancialAudit")
        self.transactions = []
        self.suspicious_activity = []
        self.daily_totals = defaultdict(lambda: defaultdict(float))
        self.user_activity = defaultdict(list)

    def update(self, context):
        """Audit financial transactions."""
        if context.state == ExecutionState.COMPLETED and context.arguments.get(
            "transaction_type"
        ):

            self._audit_transaction(context)

    def _audit_transaction(self, context):
        """Comprehensive transaction auditing."""
        transaction = {
            "timestamp": context.timestamp,
            "reference": f"TXN_{len(self.transactions)+1:06d}",
            "type": context.arguments.get("transaction_type"),
            "amount": context.arguments.get("amount", 0),
            "user_id": context.arguments.get("user_id"),
            "account_from": context.arguments.get("account_from"),
            "account_to": context.arguments.get("account_to"),
            "success": context.is_successful,
            "execution_time": (
                getattr(context.result, "execution_time", 0) if context.result else 0
            ),
        }

        if context.is_failed:
            transaction["failure_reason"] = str(context.result.exception)
            transaction["error_type"] = context.result.exception_type.__name__

        self.transactions.append(transaction)

        # Track user activity
        self.user_activity[transaction["user_id"]].append(transaction)

        # Track daily totals by transaction type
        day_key = time.strftime("%Y-%m-%d", time.localtime(context.timestamp))
        if transaction["success"]:
            self.daily_totals[day_key][transaction["type"]] += transaction["amount"]

        # Comprehensive suspicious activity detection
        if self._is_suspicious(transaction):
            self.suspicious_activity.append(transaction)
            print(
                f"🚨 SUSPICIOUS TRANSACTION: {transaction['reference']} - "
                f"${transaction['amount']:.2f} {transaction['type']} by {transaction['user_id']}"
            )

        # Real-time compliance monitoring
        if transaction["amount"] > 10000 and transaction["success"]:
            print(
                f"💰 HIGH-VALUE TRANSACTION: {transaction['reference']} - "
                f"${transaction['amount']:.2f} requires compliance review"
            )

    def _is_suspicious(self, transaction):
        """Advanced suspicious activity detection."""
        user_id = transaction["user_id"]
        amount = transaction["amount"]

        # Large transaction amount threshold
        if amount > 50000:
            return True

        # High frequency transactions from same user
        user_recent = [
            t
            for t in self.user_activity[user_id][-10:]
            if time.time() - t["timestamp"] < 300
        ]  # Last 5 minutes

        if len(user_recent) >= 5:
            return True

        # Unusual transaction patterns
        user_transactions = self.user_activity[user_id]
        if len(user_transactions) > 1:
            # Check for round number patterns (possible structuring)
            if amount % 1000 == 0 and amount < 10000:
                recent_round = sum(
                    1 for t in user_transactions[-5:] if t["amount"] % 1000 == 0
                )
                if recent_round >= 3:
                    return True

            # Check for rapid escalation in transaction amounts
            recent_amounts = [t["amount"] for t in user_transactions[-3:]]
            if len(recent_amounts) >= 3:
                if all(
                    recent_amounts[i] < recent_amounts[i + 1] * 0.5
                    for i in range(len(recent_amounts) - 1)
                ):
                    return True

        return False

    def get_financial_summary(self):
        """Generate comprehensive financial audit summary."""
        total_transactions = len(self.transactions)
        successful_transactions = sum(1 for t in self.transactions if t["success"])
        total_amount = sum(t["amount"] for t in self.transactions if t["success"])

        # Transaction type breakdown
        type_breakdown = defaultdict(lambda: {"count": 0, "total": 0})
        for txn in self.transactions:
            if txn["success"]:
                type_breakdown[txn["type"]]["count"] += 1
                type_breakdown[txn["type"]]["total"] += txn["amount"]

        # User risk analysis
        high_risk_users = []
        for user_id, transactions in self.user_activity.items():
            user_total = sum(t["amount"] for t in transactions if t["success"])
            user_suspicious = sum(
                1
                for t in transactions
                if any(
                    s["reference"] == t["reference"] for s in self.suspicious_activity
                )
            )

            if user_suspicious > 0 or user_total > 100000:
                high_risk_users.append(
                    {
                        "user_id": user_id,
                        "total_amount": user_total,
                        "transaction_count": len(transactions),
                        "suspicious_count": user_suspicious,
                    }
                )

        return {
            "total_transactions": total_transactions,
            "successful_transactions": successful_transactions,
            "failed_transactions": total_transactions - successful_transactions,
            "total_amount": total_amount,
            "suspicious_activity": len(self.suspicious_activity),
            "success_rate": (successful_transactions / max(total_transactions, 1))
            * 100,
            "transaction_types": dict(type_breakdown),
            "daily_totals": {
                day: dict(types) for day, types in self.daily_totals.items()
            },
            "high_risk_users": high_risk_users,
            "compliance_flags": len(
                [t for t in self.transactions if t["success"] and t["amount"] > 10000]
            ),
        }


# Setup custom observers
financial_observer = FinancialAuditObserver()


# Financial transaction function
@CallPyBack(
    observers=[financial_observer],
    exception_classes=(ValueError, PermissionError, RuntimeError),
    default_return={"status": "transaction_failed", "amount": 0},
)
def financial_transaction(transaction_type, user_id, amount, **kwargs):
    """Financial transaction with comprehensive auditing."""

    # Input validation
    if amount <= 0:
        raise ValueError("Transaction amount must be positive")

    # Business rule validation
    if transaction_type == "withdrawal" and amount > 50000:
        if user_id != "premium_user":
            raise PermissionError("Withdrawal limit exceeded for regular users")

    # Simulate transaction processing with realistic delays
    processing_time = random.uniform(0.01, 0.05)
    if amount > 10000:
        processing_time += random.uniform(
            0.02, 0.08
        )  # Additional processing for large amounts

    time.sleep(processing_time)

    # Simulate failure scenarios
    failure_rate = 0.03  # Base 3% failure rate
    if amount > 100000:
        failure_rate = 0.08  # Higher failure rate for very large amounts

    if random.random() < failure_rate:
        raise RuntimeError("Transaction processing error")

    return {
        "status": "success",
        "transaction_type": transaction_type,
        "amount": amount,
        "processed_at": time.time(),
        "processing_time": processing_time,
    }


if __name__ == "__main__":
    # Financial transaction simulation
    print("\n2. Running financial transaction simulation...")

    transaction_scenarios = [
        # Normal operations
        ("deposit", "user001", 1500.00),
        ("withdrawal", "user002", 800.00),
        ("transfer", "user001", 250.00),
        # Large transactions
        ("deposit", "user003", 25000.00),
        ("withdrawal", "premium_user", 75000.00),
        # Suspicious patterns - high frequency
        *[
            ("transfer", "user004", 999.00) for _ in range(4)
        ],  # Just under 1000 - structuring
        # Escalating amounts - suspicious
        ("transfer", "user005", 1000.00),
        ("transfer", "user005", 3000.00),
        ("transfer", "user005", 9000.00),
        # Very large transaction
        ("wire_transfer", "user006", 150000.00),
        # Failed transactions
        ("withdrawal", "user007", 60000.00),  # Over limit
        ("transfer", "user008", -500.00),  # Invalid amount
    ]

    for txn_type, user, amount in transaction_scenarios:
        try:
            result = financial_transaction(
                txn_type,
                user,
                amount,
                account_from=f"{user}_checking",
                account_to="external_account" if "transfer" in txn_type else None,
            )
        except Exception as e:
            print(f"Transaction failed: {e}")

    # Generate comprehensive reports
    print("\n" + "=" * 60)
    print("CUSTOM OBSERVERS ANALYSIS REPORT")
    print("=" * 60)

    financial_summary = financial_observer.get_financial_summary()

    print("\nFinancial Audit Summary:")
    print(f"  Total transactions: {financial_summary['total_transactions']}")
    print(f"  Success rate: {financial_summary['success_rate']:.1f}%")
    print(f"  Total amount processed: ${financial_summary['total_amount']:,.2f}")
    print(
        f"  Suspicious activities detected: {financial_summary['suspicious_activity']}"
    )
    print(f"  Compliance flags: {financial_summary['compliance_flags']}")

    print("  Transaction breakdown:")
    for txn_type, stats in financial_summary["transaction_types"].items():
        print(
            f"    {txn_type}: {stats['count']} transactions, "
            f"${stats['total']:,.2f} total"
        )

    if financial_summary["high_risk_users"]:
        print(
            f"  High-risk users identified: {len(financial_summary['high_risk_users'])}"
        )
        for user in financial_summary["high_risk_users"][:3]:  # Show top 3
            print(
                f"    {user['user_id']}: ${user['total_amount']:,.2f}, "
                f"{user['suspicious_count']} suspicious transactions"
            )
