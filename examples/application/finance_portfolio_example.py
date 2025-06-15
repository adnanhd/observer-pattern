#!/usr/bin/env python3
"""
Finance Portfolio Analytics - Application Example
Demonstrates parallel financial computations and risk analysis.
"""

import math
import random
import time
from dataclasses import dataclass
from typing import Dict, List

from callpyback import ExecutionMode, emit_event, on_event, plugin_session


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


# Finance event handlers
@on_event("portfolio.analysis.started")
def handle_analysis_started(message):
    portfolio_name = message.payload.get("portfolio_name", "unknown")
    analysis_type = message.payload.get("analysis_type", "unknown")
    print(f"💼 Started {analysis_type} for portfolio: {portfolio_name}")


@on_event("portfolio.analysis.completed")
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
            f"📊 Monte Carlo for {portfolio_name}: Return={expected_return:.2%}, VaR={var_95:.2%} ({duration:.2f}s)"
        )
    elif analysis_type == "risk_metrics":
        sharpe = result.get("sharpe_ratio", 0)
        max_drawdown = result.get("max_drawdown", 0)
        print(
            f"📈 Risk metrics for {portfolio_name}: Sharpe={sharpe:.3f}, MaxDD={max_drawdown:.2%} ({duration:.2f}s)"
        )
    else:
        print(f"✅ {analysis_type} completed for {portfolio_name} in {duration:.2f}s")


@on_event("market.risk.alert")
def handle_risk_alert(message):
    payload = message.payload
    alert_type = payload.get("alert_type", "unknown")
    portfolio_name = payload.get("portfolio_name", "unknown")
    severity = payload.get("severity", "medium")
    print(f"🚨 {severity.upper()} RISK ALERT: {alert_type} in {portfolio_name}")


@on_event("optimization.*.completed")
def handle_optimization_completed(message):
    optimizer_type = message.topic.split(".")[1]
    payload = message.payload
    improvement = payload.get("improvement_pct", 0)
    print(f"🎯 {optimizer_type} optimization: {improvement:.1f}% improvement")


def monte_carlo_simulation(
    portfolio: Portfolio, days: int = 252, simulations: int = 10000
) -> Dict:
    """CPU-intensive Monte Carlo portfolio simulation"""

    emit_event(
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
        # Initialize simulation parameters
        dt = 1.0 / 252  # Daily time step
        portfolio_values = []

        # Run Monte Carlo simulations (CPU intensive)
        for sim in range(simulations):
            current_value = 100000  # Starting portfolio value
            daily_values = [current_value]

            for day in range(days):
                # Generate correlated random returns for each asset
                portfolio_return = 0

                for i, (asset, weight) in enumerate(
                    zip(portfolio.assets, portfolio.weights)
                ):
                    # Random return using normal distribution
                    random_shock = random.gauss(0, 1)
                    daily_return = (
                        asset.expected_return * dt
                        + asset.volatility * math.sqrt(dt) * random_shock
                    )
                    portfolio_return += weight * daily_return

                current_value *= 1 + portfolio_return
                daily_values.append(current_value)

            portfolio_values.append(daily_values)

            # Yield control occasionally to prevent blocking
            if sim % 1000 == 0 and sim > 0:
                time.sleep(0.001)

        # Calculate statistics from simulations
        final_values = [values[-1] for values in portfolio_values]
        final_values.sort()

        # Calculate returns
        returns = [(val - 100000) / 100000 for val in final_values]

        # Risk metrics
        expected_return = sum(returns) / len(returns)
        var_95 = returns[int(0.05 * len(returns))]  # 95% VaR
        var_99 = returns[int(0.01 * len(returns))]  # 99% VaR

        # Expected annual return
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

        # Check for risk alerts
        if var_95 < -0.20:  # More than 20% loss at 95% confidence
            emit_event(
                "market.risk.alert",
                {
                    "alert_type": "high_portfolio_risk",
                    "portfolio_name": portfolio.name,
                    "var_95": var_95,
                    "severity": "high",
                },
            )

        emit_event(
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
        error_result = {
            "portfolio_name": portfolio.name,
            "analysis_type": "monte_carlo",
            "error": str(e),
            "duration": duration,
            "status": "failed",
        }

        emit_event("portfolio.analysis.failed", error_result)
        return error_result


def calculate_risk_metrics(portfolio: Portfolio) -> Dict:
    """Calculate comprehensive risk metrics"""

    emit_event(
        "portfolio.analysis.started",
        {"portfolio_name": portfolio.name, "analysis_type": "risk_metrics"},
    )

    start_time = time.time()

    try:
        # Calculate portfolio statistics
        portfolio_return = sum(
            asset.expected_return * weight
            for asset, weight in zip(portfolio.assets, portfolio.weights)
        )

        # Portfolio volatility (simplified, assumes zero correlation)
        portfolio_variance = sum(
            (asset.volatility * weight) ** 2
            for asset, weight in zip(portfolio.assets, portfolio.weights)
        )
        portfolio_volatility = math.sqrt(portfolio_variance)

        # Risk-free rate (assume 2%)
        risk_free_rate = 0.02

        # Sharpe ratio
        sharpe_ratio = (portfolio_return - risk_free_rate) / portfolio_volatility

        # Simulate historical data for additional metrics
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

        # Calculate maximum drawdown
        cumulative_returns = []
        cumulative = 1.0
        peak = 1.0
        max_drawdown = 0.0

        for ret in daily_returns:
            cumulative *= 1 + ret
            cumulative_returns.append(cumulative)

            if cumulative > peak:
                peak = cumulative
            else:
                drawdown = (peak - cumulative) / peak
                max_drawdown = max(max_drawdown, drawdown)

        # Beta calculation (simplified, using market proxy)
        market_volatility = 0.16  # Assume 16% market volatility
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
            "var_95_daily": -1.645
            * portfolio_volatility
            / math.sqrt(252),  # Parametric VaR
            "duration": duration,
            "status": "success",
        }

        emit_event(
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
        error_result = {
            "portfolio_name": portfolio.name,
            "analysis_type": "risk_metrics",
            "error": str(e),
            "duration": duration,
            "status": "failed",
        }

        emit_event("portfolio.analysis.failed", error_result)
        return error_result


def portfolio_optimization(portfolio: Portfolio, optimizer_type: str) -> Dict:
    """Optimize portfolio weights using different algorithms"""

    start_time = time.time()

    # Simulate optimization algorithm (computationally intensive)
    num_iterations = random.randint(1000, 5000)
    best_sharpe = 0
    best_weights = portfolio.weights.copy()

    for iteration in range(num_iterations):
        # Generate random weight allocation
        random_weights = [random.random() for _ in portfolio.assets]
        weight_sum = sum(random_weights)
        random_weights = [w / weight_sum for w in random_weights]  # Normalize

        # Calculate portfolio metrics for these weights
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

        # Simulate computational work
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

    emit_event(f"optimization.{optimizer_type}.completed", result)
    return result


def create_sample_portfolios() -> List[Portfolio]:
    """Create sample portfolios for analysis"""

    # Tech-heavy portfolio
    tech_assets = [
        Asset("AAPL", 150.0, 0.25, 0.12, "Technology"),
        Asset("MSFT", 300.0, 0.22, 0.11, "Technology"),
        Asset("GOOGL", 2500.0, 0.28, 0.13, "Technology"),
        Asset("NVDA", 400.0, 0.35, 0.18, "Technology"),
    ]
    tech_portfolio = Portfolio("Tech Growth", tech_assets, [0.3, 0.3, 0.25, 0.15])

    # Diversified portfolio
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

    # High-risk portfolio
    risk_assets = [
        Asset("BTC", 45000.0, 0.80, 0.25, "Crypto"),
        Asset("TSLA", 250.0, 0.45, 0.20, "Technology"),
        Asset("ARKK", 60.0, 0.35, 0.15, "Growth ETF"),
        Asset("GME", 25.0, 0.60, 0.30, "Meme Stock"),
    ]
    risk_portfolio = Portfolio("High Risk", risk_assets, [0.25, 0.35, 0.25, 0.15])

    return [tech_portfolio, diversified_portfolio, risk_portfolio]


def main():
    """Demo parallel financial analysis"""
    print("💼 Finance Portfolio Analytics")
    print("=" * 50)

    portfolios = create_sample_portfolios()

    with plugin_session() as manager:
        # Configure for compute-intensive financial calculations
        manager.configure().processes(3).max_threads(4).execution_mode(
            ExecutionMode.HYBRID
        ).apply()

        print(f"📊 Analyzing {len(portfolios)} portfolios with parallel processing...")

        # 1. Run Monte Carlo simulations in parallel
        print("\n🎲 Running Monte Carlo simulations...")
        mc_start = time.time()
        mc_results = manager.map_parallel(
            lambda p: monte_carlo_simulation(p, days=252, simulations=8000), portfolios
        )
        mc_duration = time.time() - mc_start

        print(
            f"   Completed {len(mc_results)} Monte Carlo analyses in {mc_duration:.2f}s"
        )

        # 2. Calculate risk metrics in parallel
        print("\n📈 Calculating risk metrics...")
        risk_results = manager.map_parallel(calculate_risk_metrics, portfolios)

        # 3. Run portfolio optimizations in parallel
        print("\n🎯 Running portfolio optimizations...")
        optimization_tasks = [
            (portfolios[0], "mean_variance"),
            (portfolios[1], "risk_parity"),
            (portfolios[2], "maximum_sharpe"),
        ]

        opt_results = manager.parallel(
            *[
                lambda p=p, opt=opt: portfolio_optimization(p, opt)
                for p, opt in optimization_tasks
            ]
        )

        # Summarize results
        print(f"\n📋 Analysis Summary:")
        for i, portfolio in enumerate(portfolios):
            mc_result = mc_results[i] if i < len(mc_results) else {}
            risk_result = risk_results[i] if i < len(risk_results) else {}

            if mc_result.get("status") == "success":
                expected_ret = mc_result.get("expected_annual_return", 0)
                var_95 = mc_result.get("var_95", 0)
                print(
                    f"   {portfolio.name}: Expected Return {expected_ret:.1%}, VaR95 {var_95:.1%}"
                )

            if risk_result.get("status") == "success":
                sharpe = risk_result.get("sharpe_ratio", 0)
                max_dd = risk_result.get("max_drawdown", 0)
                print(f"     → Sharpe: {sharpe:.2f}, Max Drawdown: {max_dd:.1%}")

        # Show system performance
        metrics = manager.get_metrics()
        print(f"\n📈 System Performance:")
        print(f"   Total computations: {metrics['tasks_completed']}")
        print(f"   Events generated: {metrics['events_published']}")
        print(f"   Process utilization: {metrics.get('process_executor', 'N/A')}")
        print(f"   Health status: {manager.health_check()}")


if __name__ == "__main__":
    main()
