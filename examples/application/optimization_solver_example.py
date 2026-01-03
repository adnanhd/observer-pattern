#!/usr/bin/env python3
"""
Optimization Solver Server - Application Example

Demonstrates a load-balanced optimization solver pattern where:
- Multiple clients submit optimization problems to a queue
- N solver instances (limited by max_instances) process requests concurrently
- Results are published back to clients via response topics

This is similar to how a Gurobi server would work, but uses a simple
local ILP solver implementation for demonstration.
"""

import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from callpyback import (
    ExecutionMode,
    Executor,
    MessageQueue,
    MetricsObserver,
    TimingObserver,
    task,
)

# ============================================================================
# Simple ILP Solver Implementation (Local, no external dependencies)
# ============================================================================


class OptimizationType(str, Enum):
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


@dataclass
class Variable:
    """Decision variable for optimization."""

    name: str
    lower_bound: float = 0.0
    upper_bound: float = float("inf")
    is_integer: bool = True
    value: Optional[float] = None


@dataclass
class Constraint:
    """Linear constraint: sum(coeffs[i] * vars[i]) <= rhs."""

    name: str
    coefficients: Dict[str, float]  # var_name -> coefficient
    rhs: float
    sense: str = "<="  # "<=", ">=", "=="


@dataclass
class OptimizationProblem:
    """Integer Linear Programming problem definition."""

    problem_id: str
    name: str
    optimization_type: OptimizationType
    objective: Dict[str, float]  # var_name -> coefficient
    constraints: List[Constraint]
    variables: Dict[str, Variable]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OptimizationResult:
    """Result of solving an optimization problem."""

    problem_id: str
    status: str  # "optimal", "infeasible", "unbounded", "timeout"
    objective_value: Optional[float] = None
    variable_values: Dict[str, float] = field(default_factory=dict)
    solve_time: float = 0.0
    iterations: int = 0
    gap: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class SimpleILPSolver:
    """Simple ILP solver using branch-and-bound with rounding heuristics.

    This is a demonstration solver - not production-grade.
    For real applications, use Gurobi, CPLEX, or OR-Tools.
    """

    def __init__(self, time_limit: float = 10.0, max_iterations: int = 10000):
        self.time_limit = time_limit
        self.max_iterations = max_iterations

    def solve(self, problem: OptimizationProblem) -> OptimizationResult:
        """Solve the optimization problem."""
        start_time = time.time()
        iterations = 0

        # Initialize variables at lower bounds
        solution = {name: var.lower_bound for name, var in problem.variables.items()}

        best_solution = solution.copy()
        best_objective = self._evaluate_objective(problem, solution)

        # Simple iterative improvement heuristic
        improved = True
        while improved and iterations < self.max_iterations:
            if time.time() - start_time > self.time_limit:
                return OptimizationResult(
                    problem_id=problem.problem_id,
                    status="timeout",
                    objective_value=best_objective,
                    variable_values=best_solution,
                    solve_time=time.time() - start_time,
                    iterations=iterations,
                )

            improved = False
            iterations += 1

            for var_name, var in problem.variables.items():
                # Try incrementing this variable
                current_val = solution[var_name]

                if var.is_integer:
                    new_val = current_val + 1
                else:
                    new_val = current_val + 0.1

                if new_val <= var.upper_bound:
                    solution[var_name] = new_val

                    if self._is_feasible(problem, solution):
                        new_obj = self._evaluate_objective(problem, solution)

                        is_better = (
                            problem.optimization_type == OptimizationType.MAXIMIZE
                            and new_obj > best_objective
                        ) or (
                            problem.optimization_type == OptimizationType.MINIMIZE
                            and new_obj < best_objective
                        )

                        if is_better:
                            best_solution = solution.copy()
                            best_objective = new_obj
                            improved = True
                        else:
                            solution[var_name] = current_val
                    else:
                        solution[var_name] = current_val

        # Check final feasibility
        if not self._is_feasible(problem, best_solution):
            return OptimizationResult(
                problem_id=problem.problem_id,
                status="infeasible",
                solve_time=time.time() - start_time,
                iterations=iterations,
            )

        return OptimizationResult(
            problem_id=problem.problem_id,
            status="optimal",
            objective_value=best_objective,
            variable_values=best_solution,
            solve_time=time.time() - start_time,
            iterations=iterations,
            gap=0.0,  # Simple solver doesn't compute gap
        )

    def _evaluate_objective(
        self, problem: OptimizationProblem, solution: Dict[str, float]
    ) -> float:
        """Evaluate the objective function."""
        return sum(
            coef * solution.get(var_name, 0)
            for var_name, coef in problem.objective.items()
        )

    def _is_feasible(
        self, problem: OptimizationProblem, solution: Dict[str, float]
    ) -> bool:
        """Check if solution satisfies all constraints."""
        for constraint in problem.constraints:
            lhs = sum(
                coef * solution.get(var_name, 0)
                for var_name, coef in constraint.coefficients.items()
            )

            if constraint.sense == "<=":
                if lhs > constraint.rhs + 1e-6:
                    return False
            elif constraint.sense == ">=":
                if lhs < constraint.rhs - 1e-6:
                    return False
            elif constraint.sense == "==":
                if abs(lhs - constraint.rhs) > 1e-6:
                    return False

        # Check variable bounds
        for var_name, var in problem.variables.items():
            val = solution.get(var_name, 0)
            if val < var.lower_bound - 1e-6 or val > var.upper_bound + 1e-6:
                return False

        return True


# ============================================================================
# Problem Generators (for testing)
# ============================================================================


def generate_knapsack_problem(
    problem_id: str,
    num_items: int = 10,
    capacity: int = 50,
) -> OptimizationProblem:
    """Generate a random knapsack problem."""
    variables = {}
    objective = {}
    weights = {}

    for i in range(num_items):
        var_name = f"x_{i}"
        variables[var_name] = Variable(
            name=var_name,
            lower_bound=0,
            upper_bound=1,
            is_integer=True,
        )
        # Random value and weight
        objective[var_name] = random.randint(1, 20)  # Value
        weights[var_name] = random.randint(1, 15)  # Weight

    constraints = [
        Constraint(
            name="capacity",
            coefficients=weights,
            rhs=capacity,
            sense="<=",
        )
    ]

    return OptimizationProblem(
        problem_id=problem_id,
        name=f"Knapsack_{num_items}",
        optimization_type=OptimizationType.MAXIMIZE,
        objective=objective,
        constraints=constraints,
        variables=variables,
        metadata={"type": "knapsack", "num_items": num_items, "capacity": capacity},
    )


def generate_assignment_problem(
    problem_id: str,
    num_workers: int = 5,
    num_tasks: int = 5,
) -> OptimizationProblem:
    """Generate a random assignment problem."""
    variables = {}
    objective = {}

    # x_i_j = 1 if worker i assigned to task j
    for i in range(num_workers):
        for j in range(num_tasks):
            var_name = f"x_{i}_{j}"
            variables[var_name] = Variable(
                name=var_name,
                lower_bound=0,
                upper_bound=1,
                is_integer=True,
            )
            objective[var_name] = random.randint(1, 10)  # Cost

    constraints = []

    # Each worker assigned to at most one task
    for i in range(num_workers):
        coeffs = {f"x_{i}_{j}": 1 for j in range(num_tasks)}
        constraints.append(
            Constraint(
                name=f"worker_{i}",
                coefficients=coeffs,
                rhs=1,
                sense="<=",
            )
        )

    # Each task assigned to at most one worker
    for j in range(num_tasks):
        coeffs = {f"x_{i}_{j}": 1 for i in range(num_workers)}
        constraints.append(
            Constraint(
                name=f"task_{j}",
                coefficients=coeffs,
                rhs=1,
                sense="<=",
            )
        )

    return OptimizationProblem(
        problem_id=problem_id,
        name=f"Assignment_{num_workers}x{num_tasks}",
        optimization_type=OptimizationType.MINIMIZE,
        objective=objective,
        constraints=constraints,
        variables=variables,
        metadata={
            "type": "assignment",
            "num_workers": num_workers,
            "num_tasks": num_tasks,
        },
    )


# ============================================================================
# Solver Server Setup
# ============================================================================


def create_solver_server(
    queue: MessageQueue,
    num_solvers: int = 3,
    time_limit: float = 5.0,
) -> Tuple[Any, TimingObserver, MetricsObserver]:
    """Create a load-balanced solver server.

    Args:
        queue: MessageQueue for receiving problems
        num_solvers: Maximum concurrent solver instances
        time_limit: Time limit per problem in seconds

    Returns:
        Tuple of (solver_task, timing_observer, metrics_observer)
    """
    # Create shared solver instance
    solver = SimpleILPSolver(time_limit=time_limit)

    # Observers for monitoring
    timing = TimingObserver(name="solver")
    metrics = MetricsObserver(name="solver")

    @task(
        queue=queue,
        topic="solver.problem",
        max_instances=num_solvers,  # Load balancing!
        on_execute=[timing, metrics],
        publish_result=True,
    )
    def solve_problem(**problem_dict) -> Dict[str, Any]:
        """Solve an optimization problem.

        This task is limited to num_solvers concurrent executions.
        Additional requests will queue until a slot is available.

        Note: Uses **kwargs because queue handler unpacks dict payloads.
        """
        # Reconstruct problem from dict
        problem = OptimizationProblem(
            problem_id=problem_dict["problem_id"],
            name=problem_dict["name"],
            optimization_type=OptimizationType(problem_dict["optimization_type"]),
            objective=problem_dict["objective"],
            constraints=[
                Constraint(
                    name=c["name"],
                    coefficients=c["coefficients"],
                    rhs=c["rhs"],
                    sense=c.get("sense", "<="),
                )
                for c in problem_dict["constraints"]
            ],
            variables={
                name: Variable(
                    name=name,
                    lower_bound=v.get("lower_bound", 0),
                    upper_bound=v.get("upper_bound", float("inf")),
                    is_integer=v.get("is_integer", True),
                )
                for name, v in problem_dict["variables"].items()
            },
            metadata=problem_dict.get("metadata", {}),
        )

        # Solve
        result = solver.solve(problem)

        # Return as dict
        return {
            "problem_id": result.problem_id,
            "status": result.status,
            "objective_value": result.objective_value,
            "variable_values": result.variable_values,
            "solve_time": result.solve_time,
            "iterations": result.iterations,
            "gap": result.gap,
        }

    return solve_problem, timing, metrics


def problem_to_dict(problem: OptimizationProblem) -> Dict[str, Any]:
    """Convert problem to dict for queue transport."""
    return {
        "problem_id": problem.problem_id,
        "name": problem.name,
        "optimization_type": problem.optimization_type.value,
        "objective": problem.objective,
        "constraints": [
            {
                "name": c.name,
                "coefficients": c.coefficients,
                "rhs": c.rhs,
                "sense": c.sense,
            }
            for c in problem.constraints
        ],
        "variables": {
            name: {
                "lower_bound": v.lower_bound,
                "upper_bound": v.upper_bound,
                "is_integer": v.is_integer,
            }
            for name, v in problem.variables.items()
        },
        "metadata": problem.metadata,
    }


# ============================================================================
# Main Demo
# ============================================================================


def main():
    """Demo the optimization solver server."""
    print("=" * 60)
    print("Optimization Solver Server Example")
    print("=" * 60)

    # Setup
    queue = MessageQueue()
    NUM_SOLVERS = 3
    NUM_PROBLEMS = 10

    # Create solver server with load balancing
    solve_task, timing, metrics = create_solver_server(
        queue=queue,
        num_solvers=NUM_SOLVERS,
        time_limit=2.0,
    )

    print(f"\nSolver server started with {NUM_SOLVERS} concurrent instances")
    print(f"Pool stats: {solve_task.pool.stats}")

    # Collect results
    results = []
    results_lock = threading.Lock()

    @queue.on("solver.problem.success")
    def on_success(msg):
        with results_lock:
            results.append(("success", msg.payload))

    @queue.on("solver.problem.failure")
    def on_failure(msg):
        with results_lock:
            results.append(("failure", msg.payload))

    # Generate problems
    print(f"\nGenerating {NUM_PROBLEMS} optimization problems...")
    problems = []
    for i in range(NUM_PROBLEMS):
        if i % 2 == 0:
            problem = generate_knapsack_problem(
                f"problem_{i:03d}",
                num_items=random.randint(5, 15),
                capacity=random.randint(20, 50),
            )
        else:
            problem = generate_assignment_problem(
                f"problem_{i:03d}",
                num_workers=random.randint(3, 6),
                num_tasks=random.randint(3, 6),
            )
        problems.append(problem)

    # Submit problems concurrently (simulating multiple clients)
    print(f"\nSubmitting {NUM_PROBLEMS} problems to solver queue...")
    print("(Only {NUM_SOLVERS} will run concurrently due to max_instances)")

    start_time = time.time()

    # Submit all problems via queue
    for problem in problems:
        queue.publish("solver.problem", problem_to_dict(problem))

    # Also test direct calls in parallel threads
    direct_results = []

    def direct_call(problem):
        result = solve_task(problem_to_dict(problem))
        direct_results.append(result)

    # Wait for queue-triggered solves to complete
    time.sleep(0.5)

    # Check pool stats during execution
    print(f"\nPool stats during execution: {solve_task.pool.stats}")

    # Wait for all to complete
    while len(results) < NUM_PROBLEMS:
        time.sleep(0.1)
        if time.time() - start_time > 30:
            print("Timeout waiting for results")
            break

    total_time = time.time() - start_time

    # Summary
    print(f"\n{'=' * 60}")
    print("Results Summary:")
    print(f"{'=' * 60}")

    successes = [r for r in results if r[0] == "success"]
    failures = [r for r in results if r[0] == "failure"]

    print(f"\nTotal problems: {NUM_PROBLEMS}")
    print(f"Successful: {len(successes)}")
    print(f"Failed: {len(failures)}")
    print(f"Total time: {total_time:.2f}s")

    if successes:
        avg_solve_time = sum(r[1]["result"]["solve_time"] for r in successes) / len(
            successes
        )
        print(f"Average solve time: {avg_solve_time:.3f}s")

    # Solver statistics
    print(f"\nSolver Timing Stats:")
    print(f"  Count: {timing.stats['count']}")
    print(f"  Avg: {timing.stats['avg'] * 1000:.2f}ms")
    print(f"  Min: {timing.stats['min'] * 1000:.2f}ms")
    print(f"  Max: {timing.stats['max'] * 1000:.2f}ms")
    print(f"\nSolver Metrics:")
    print(f"  Calls: {metrics.stats['calls']}")
    print(f"  Successes: {metrics.stats['successes']}")
    print(f"  Success rate: {metrics.stats['success_rate']:.1%}")

    print(f"\nFinal Pool Stats: {solve_task.pool.stats}")

    # Show some results
    print(f"\nSample Results:")
    for i, (status, payload) in enumerate(results[:3]):
        result = payload["result"]
        print(f"  Problem {result['problem_id']}:")
        print(f"    Status: {result['status']}")
        print(f"    Objective: {result['objective_value']}")
        print(f"    Solve time: {result['solve_time']:.3f}s")
        print(f"    Iterations: {result['iterations']}")

    print(f"\n{'=' * 60}")
    print("Demo demonstrates:")
    print("  - Load-balanced task execution with max_instances")
    print("  - Queue-based problem submission")
    print("  - Concurrent solver instances with automatic queuing")
    print("  - Observer-based performance monitoring")
    print("  - Pool statistics for load monitoring")
    print("=" * 60)


if __name__ == "__main__":
    main()
