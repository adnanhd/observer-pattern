#!/usr/bin/env python3
"""
Finance Portfolio Analytics - Application Example
Demonstrates parallel financial computations and risk analysis using v3 API.
"""

import math
import random
import time
from dataclasses import dataclass
from typing import Dict, List

from callpyback import (
    ExecutionMode,
    Executor,
    MessageQueue,
    MetricsObserver,
    TimingObserver,
    observe,
)


@dataclass
class Asset:
    symbol: str
    price: float
    volatility: float  # Annual volatility
    expected_return: float  # Annual expected return
    sector: str


@dataclass
class Portfolio:
    name: str
    assets: List[Asset]
    weights: List[float]  # Portfolio weights (sum to 1.0)
    cash: float = 0.0


# Create observers for profiling
mc_timing = TimingObserver(name="monte_carlo")
risk_timing = TimingObserver(name="risk_metrics")
opt_timing = TimingObserver(name="optimization")
metrics = MetricsObserver()


def setup_event_handlers(queue: MessageQueue):
    """Setup message queue event handlers for finance events."""

    @queue.on("portfolio.analysis.started")
    def handle_analysis_started(message):
        portfolio_name = message.payload.get("portfolio_name", "unknown")
        analysis_type = message.payload.get("analysis_type", "unknown")
        print(f"  [Analysis] Started {analysis_type} for {portfolio_name}")

    @queue.on("portfolio.analysis.completed")
    def handle_analysis_completed(message):
        payload = message.payload
        portfolio_name = payload.get("portfolio_name", "unknown")
        analysis_type = payload.get("analysis_type", "unknown")
        result = payload.get("result", {})
        duration = payload.get("duration", 0)

        if analysis_type == "monte_carlo":
            expected_return = result.get("expected_annual_return", 0)
            var_95 = result.get("var_95", 0)
            print(
                f"  [Monte Carlo] {portfolio_name}: Return={expected_return:.2%}, VaR={var_95:.2%} ({duration:.2f}s)"
            )
        elif analysis_type == "risk_metrics":
            sharpe = result.get("sharpe_ratio", 0)
            max_drawdown = result.get("max_drawdown", 0)
            print(
                f"  [Risk] {portfolio_name}: Sharpe={sharpe:.3f}, MaxDD={max_drawdown:.2%} ({duration:.2f}s)"
            )

    @queue.on("market.risk.alert")
    def handle_risk_alert(message):
        payload = message.payload
        alert_type = payload.get("alert_type", "unknown")
        portfolio_name = payload.get("portfolio_name", "unknown")
        severity = payload.get("severity", "medium")
        print(f"  [ALERT] {severity.upper()}: {alert_type} in {portfolio_name}")

    @queue.on("optimization.*.completed")
    def handle_optimization_completed(message):
        optimizer_type = message.topic.split(".")[1]
        payload = message.payload
        improvement = payload.get("improvement_pct", 0)
        print(f"  [Optimization] {optimizer_type}: {improvement:.1f}% improvement")


@observe(mc_timing, metrics)
def monte_carlo_simulation(
    portfolio: Portfolio,
    queue: MessageQueue,
    days: int = 252,
    simulations: int = 10000,
) -> Dict:
    """CPU-intensive Monte Carlo portfolio simulation."""

    queue.publish(
        "portfolio.analysis.started",
        {
            "portfolio_name": portfolio.name,
            "analysis_type": "monte_carlo",
            "simulations": simulations,
            "days": days,
        },
    )

    start_time = time.time()

    try:
        dt = 1.0 / 252
        portfolio_values = []

        for sim in range(simulations):
            current_value = 100000
            daily_values = [current_value]

            for day in range(days):
                portfolio_return = 0

                for i, (asset, weight) in enumerate(
                    zip(portfolio.assets, portfolio.weights)
                ):
                    random_shock = random.gauss(0, 1)
                    daily_return = (
                        asset.expected_return * dt
                        + asset.volatility * math.sqrt(dt) * random_shock
                    )
                    portfolio_return += weight * daily_return

                current_value *= 1 + portfolio_return
                daily_values.append(current_value)

            portfolio_values.append(daily_values)

            if sim % 1000 == 0 and sim > 0:
                time.sleep(0.001)

        final_values = [values[-1] for values in portfolio_values]
        final_values.sort()

        returns = [(val - 100000) / 100000 for val in final_values]

        expected_return = sum(returns) / len(returns)
        var_95 = returns[int(0.05 * len(returns))]
        var_99 = returns[int(0.01 * len(returns))]

        expected_annual_return = (1 + expected_return) ** (252.0 / days) - 1

        duration = time.time() - start_time

        result = {
            "portfolio_name": portfolio.name,
            "analysis_type": "monte_carlo",
            "simulations": simulations,
            "expected_annual_return": expected_annual_return,
            "var_95": var_95,
            "var_99": var_99,
            "best_case": max(returns),
            "worst_case": min(returns),
            "duration": duration,
            "status": "success",
        }

        if var_95 < -0.20:
            queue.publish(
                "market.risk.alert",
                {
                    "alert_type": "high_portfolio_risk",
                    "portfolio_name": portfolio.name,
                    "var_95": var_95,
                    "severity": "high",
                },
            )

        queue.publish(
            "portfolio.analysis.completed",
            {
                "portfolio_name": portfolio.name,
                "analysis_type": "monte_carlo",
                "result": result,
                "duration": duration,
            },
        )

        return result

    except Exception as e:
        duration = time.time() - start_time
        return {
            "portfolio_name": portfolio.name,
            "analysis_type": "monte_carlo",
            "error": str(e),
            "duration": duration,
            "status": "failed",
        }


@observe(risk_timing, metrics)
def calculate_risk_metrics(portfolio: Portfolio, queue: MessageQueue) -> Dict:
    """Calculate comprehensive risk metrics."""

    queue.publish(
        "portfolio.analysis.started",
        {"portfolio_name": portfolio.name, "analysis_type": "risk_metrics"},
    )

    start_time = time.time()

    try:
        portfolio_return = sum(
            asset.expected_return * weight
            for asset, weight in zip(portfolio.assets, portfolio.weights)
        )

        portfolio_variance = sum(
            (asset.volatility * weight) ** 2
            for asset, weight in zip(portfolio.assets, portfolio.weights)
        )
        portfolio_volatility = math.sqrt(portfolio_variance)

        risk_free_rate = 0.02
        sharpe_ratio = (portfolio_return - risk_free_rate) / portfolio_volatility

        # Simulate historical data
        days = 252
        daily_returns = []

        for _ in range(days):
            daily_return = 0
            for asset, weight in zip(portfolio.assets, portfolio.weights):
                asset_return = random.gauss(
                    asset.expected_return / 252, asset.volatility / math.sqrt(252)
                )
                daily_return += weight * asset_return
            daily_returns.append(daily_return)

        # Maximum drawdown
        cumulative = 1.0
        peak = 1.0
        max_drawdown = 0.0

        for ret in daily_returns:
            cumulative *= 1 + ret
            if cumulative > peak:
                peak = cumulative
            else:
                drawdown = (peak - cumulative) / peak
                max_drawdown = max(max_drawdown, drawdown)

        market_volatility = 0.16
        beta = portfolio_volatility / market_volatility

        duration = time.time() - start_time

        result = {
            "portfolio_name": portfolio.name,
            "analysis_type": "risk_metrics",
            "expected_return": portfolio_return,
            "volatility": portfolio_volatility,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": max_drawdown,
            "beta": beta,
            "var_95_daily": -1.645 * portfolio_volatility / math.sqrt(252),
            "duration": duration,
            "status": "success",
        }

        queue.publish(
            "portfolio.analysis.completed",
            {
                "portfolio_name": portfolio.name,
                "analysis_type": "risk_metrics",
                "result": result,
                "duration": duration,
            },
        )

        return result

    except Exception as e:
        duration = time.time() - start_time
        return {
            "portfolio_name": portfolio.name,
            "analysis_type": "risk_metrics",
            "error": str(e),
            "duration": duration,
            "status": "failed",
        }


@observe(opt_timing, metrics)
def portfolio_optimization(
    portfolio: Portfolio, queue: MessageQueue, optimizer_type: str
) -> Dict:
    """Optimize portfolio weights using iterative methods."""

    start_time = time.time()

    num_iterations = random.randint(1000, 5000)
    best_sharpe = 0
    best_weights = portfolio.weights.copy()

    for iteration in range(num_iterations):
        random_weights = [random.random() for _ in portfolio.assets]
        weight_sum = sum(random_weights)
        random_weights = [w / weight_sum for w in random_weights]

        portfolio_return = sum(
            asset.expected_return * weight
            for asset, weight in zip(portfolio.assets, random_weights)
        )
        portfolio_variance = sum(
            (asset.volatility * weight) ** 2
            for asset, weight in zip(portfolio.assets, random_weights)
        )
        portfolio_volatility = math.sqrt(portfolio_variance)

        sharpe = (portfolio_return - 0.02) / portfolio_volatility

        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_weights = random_weights.copy()

        if iteration % 500 == 0:
            time.sleep(0.001)

    # Calculate improvement
    original_return = sum(
        asset.expected_return * weight
        for asset, weight in zip(portfolio.assets, portfolio.weights)
    )
    original_variance = sum(
        (asset.volatility * weight) ** 2
        for asset, weight in zip(portfolio.assets, portfolio.weights)
    )
    original_sharpe = (original_return - 0.02) / math.sqrt(original_variance)

    improvement_pct = ((best_sharpe - original_sharpe) / abs(original_sharpe)) * 100

    duration = time.time() - start_time

    result = {
        "portfolio_name": portfolio.name,
        "optimizer_type": optimizer_type,
        "original_sharpe": original_sharpe,
        "optimized_sharpe": best_sharpe,
        "improvement_pct": improvement_pct,
        "optimal_weights": best_weights,
        "iterations": num_iterations,
        "duration": duration,
    }

    queue.publish(f"optimization.{optimizer_type}.completed", result)
    return result


def create_sample_portfolios() -> List[Portfolio]:
    """Create sample portfolios for analysis."""

    tech_assets = [
        Asset("AAPL", 150.0, 0.25, 0.12, "Technology"),
        Asset("MSFT", 300.0, 0.22, 0.11, "Technology"),
        Asset("GOOGL", 2500.0, 0.28, 0.13, "Technology"),
        Asset("NVDA", 400.0, 0.35, 0.18, "Technology"),
    ]
    tech_portfolio = Portfolio("Tech Growth", tech_assets, [0.3, 0.3, 0.25, 0.15])

    diversified_assets = [
        Asset("SPY", 400.0, 0.16, 0.10, "Index"),
        Asset("BND", 80.0, 0.05, 0.03, "Bonds"),
        Asset("GLD", 180.0, 0.20, 0.05, "Commodities"),
        Asset("VTI", 220.0, 0.18, 0.09, "Index"),
        Asset("REIT", 90.0, 0.25, 0.08, "Real Estate"),
    ]
    diversified_portfolio = Portfolio(
        "Balanced", diversified_assets, [0.4, 0.2, 0.1, 0.2, 0.1]
    )

    risk_assets = [
        Asset("BTC", 45000.0, 0.80, 0.25, "Crypto"),
        Asset("TSLA", 250.0, 0.45, 0.20, "Technology"),
        Asset("ARKK", 60.0, 0.35, 0.15, "Growth ETF"),
        Asset("GME", 25.0, 0.60, 0.30, "Meme Stock"),
    ]
    risk_portfolio = Portfolio("High Risk", risk_assets, [0.25, 0.35, 0.25, 0.15])

    return [tech_portfolio, diversified_portfolio, risk_portfolio]


def main():
    """Demo parallel financial analysis."""
    print("Finance Portfolio Analytics")
    print("=" * 50)

    # Setup
    queue = MessageQueue()
    setup_event_handlers(queue)

    portfolios = create_sample_portfolios()
    executor = Executor(mode=ExecutionMode.THREAD, max_workers=6)

    print(f"Analyzing {len(portfolios)} portfolios with parallel processing...\n")

    with executor:
        # 1. Run Monte Carlo simulations in parallel
        print("Running Monte Carlo simulations...")
        mc_start = time.time()

        mc_task_ids = []
        for p in portfolios:
            task_id = executor.submit(monte_carlo_simulation, p, queue, 252, 8000)
            mc_task_ids.append(task_id)

        mc_results = [executor.result(tid).value for tid in mc_task_ids]
        mc_duration = time.time() - mc_start
        print(
            f"Completed {len(mc_results)} Monte Carlo analyses in {mc_duration:.2f}s\n"
        )

        # 2. Calculate risk metrics in parallel
        print("Calculating risk metrics...")
        risk_task_ids = []
        for p in portfolios:
            task_id = executor.submit(calculate_risk_metrics, p, queue)
            risk_task_ids.append(task_id)

        risk_results = [executor.result(tid).value for tid in risk_task_ids]

        # 3. Run portfolio optimizations in parallel
        print("\nRunning portfolio optimizations...")
        optimization_tasks = [
            (portfolios[0], "mean_variance"),
            (portfolios[1], "risk_parity"),
            (portfolios[2], "maximum_sharpe"),
        ]

        opt_task_ids = []
        for p, opt_type in optimization_tasks:
            task_id = executor.submit(portfolio_optimization, p, queue, opt_type)
            opt_task_ids.append(task_id)

        opt_results = [executor.result(tid).value for tid in opt_task_ids]

    # Summarize results
    print(f"\n{'=' * 50}")
    print("Analysis Summary:")

    for i, portfolio in enumerate(portfolios):
        mc_result = mc_results[i] if i < len(mc_results) else {}
        risk_result = risk_results[i] if i < len(risk_results) else {}

        print(f"\n  {portfolio.name}:")
        if mc_result.get("status") == "success":
            expected_ret = mc_result.get("expected_annual_return", 0)
            var_95 = mc_result.get("var_95", 0)
            print(f"    Expected Return: {expected_ret:.1%}, VaR95: {var_95:.1%}")

        if risk_result.get("status") == "success":
            sharpe = risk_result.get("sharpe_ratio", 0)
            max_dd = risk_result.get("max_drawdown", 0)
            print(f"    Sharpe Ratio: {sharpe:.2f}, Max Drawdown: {max_dd:.1%}")

    # Observer statistics
    print(f"\nProfiling Statistics:")
    print(
        f"  Monte Carlo: {mc_timing.stats['count']} runs, avg {mc_timing.stats['avg']:.2f}s"
    )
    print(
        f"  Risk Metrics: {risk_timing.stats['count']} runs, avg {risk_timing.stats['avg']:.2f}s"
    )
    print(
        f"  Optimization: {opt_timing.stats['count']} runs, avg {opt_timing.stats['avg']:.2f}s"
    )
    print(
        f"  Total computations: {metrics.stats['calls']}, success rate: {metrics.stats['success_rate']:.1%}"
    )

    print(f"\nFinance Analytics demonstrates:")
    print(f"  - Monte Carlo simulations with MessageQueue events")
    print(f"  - Risk metrics calculation (Sharpe, VaR, Drawdown)")
    print(f"  - Portfolio optimization with iterative methods")
    print(f"  - Parallel execution with Executor")
    print(f"  - Observer-based profiling (TimingObserver, MetricsObserver)")


if __name__ == "__main__":
    main()
