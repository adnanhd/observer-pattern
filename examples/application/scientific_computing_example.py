#!/usr/bin/env python3
"""
Scientific Computing Simulation - Application Example
Demonstrates parallel scientific computations and simulations.
"""

import math
import random
import time
from dataclasses import dataclass
from typing import Dict, List

from callpyback import ExecutionMode, emit_event, on_event, execution_session


@dataclass
class Particle:
    id: int
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    mass: float
    charge: float = 0.0


@dataclass
class SimulationParams:
    time_step: float
    total_steps: int
    temperature: float
    pressure: float
    box_size: float


@dataclass
class ClimateGridCell:
    lat: float
    lon: float
    temperature: float
    humidity: float
    pressure: float
    wind_speed: float
    wind_direction: float


# Scientific computing event handlers
@on_event("simulation.*.started")
def handle_simulation_started(message):
    sim_type = message.topic.split(".")[1]
    sim_id = message.payload.get("simulation_id", "unknown")
    params = message.payload.get("parameters", {})
    print(f"🔬 {sim_type} simulation {sim_id} started: {params}")


@on_event("simulation.*.completed")
def handle_simulation_completed(message):
    sim_type = message.topic.split(".")[1]
    sim_id = message.payload.get("simulation_id", "unknown")
    compute_time = message.payload.get("compute_time", 0)
    steps = message.payload.get("steps_completed", 0)
    print(
        f"✅ {sim_type} simulation {sim_id} completed: {steps} steps in {compute_time:.2f}s"
    )


@on_event("simulation.checkpoint")
def handle_simulation_checkpoint(message):
    """Handle simulation checkpoints for long-running calculations"""
    payload = message.payload
    sim_id = payload.get("simulation_id", "unknown")
    progress = payload.get("progress_percent", 0)
    current_step = payload.get("current_step", 0)
    print(f"📊 Checkpoint {sim_id}: {progress:.1f}% complete (step {current_step})")


@on_event("analysis.convergence.*")
def handle_convergence_analysis(message):
    """Handle convergence analysis results"""
    analysis_type = message.topic.split(".")[-1]
    payload = message.payload
    converged = payload.get("converged", False)
    iterations = payload.get("iterations", 0)
    error = payload.get("final_error", 0)
    print(
        f"📈 {analysis_type} convergence: {'✅' if converged else '❌'} "
        f"after {iterations} iterations (error: {error:.6f})"
    )


def molecular_dynamics_simulation(
    sim_id: str, particles: List[Particle], params: SimulationParams
) -> Dict:
    """CPU-intensive molecular dynamics simulation"""

    emit_event(
        "simulation.md.started",
        {
            "simulation_id": sim_id,
            "parameters": {
                "particle_count": len(particles),
                "time_step": params.time_step,
                "total_steps": params.total_steps,
                "temperature": params.temperature,
            },
        },
    )

    start_time = time.time()

    try:
        # Initialize simulation state
        current_particles = [Particle(**particle.__dict__) for particle in particles]
        energies = []
        checkpoint_interval = max(1, params.total_steps // 10)

        # Main simulation loop (CPU intensive)
        for step in range(params.total_steps):
            total_kinetic_energy = 0
            total_potential_energy = 0

            # Calculate forces and update positions (O(N²) complexity)
            forces = [(0.0, 0.0, 0.0) for _ in current_particles]

            for i, particle_i in enumerate(current_particles):
                for j, particle_j in enumerate(current_particles):
                    if i != j:
                        # Calculate distance
                        dx = particle_j.x - particle_i.x
                        dy = particle_j.y - particle_i.y
                        dz = particle_j.z - particle_i.z

                        # Apply periodic boundary conditions
                        dx = dx - params.box_size * round(dx / params.box_size)
                        dy = dy - params.box_size * round(dy / params.box_size)
                        dz = dz - params.box_size * round(dz / params.box_size)

                        r = math.sqrt(dx * dx + dy * dy + dz * dz)

                        if r > 0.1:  # Avoid division by zero
                            # Lennard-Jones potential
                            sigma = 1.0
                            epsilon = 1.0
                            r6 = (sigma / r) ** 6
                            r12 = r6 * r6

                            force_magnitude = 24 * epsilon * (2 * r12 - r6) / (r * r)

                            fx = force_magnitude * dx / r
                            fy = force_magnitude * dy / r
                            fz = force_magnitude * dz / r

                            forces[i] = (
                                forces[i][0] + fx,
                                forces[i][1] + fy,
                                forces[i][2] + fz,
                            )

                            # Add to potential energy
                            potential = 4 * epsilon * (r12 - r6)
                            total_potential_energy += (
                                potential / 2
                            )  # Avoid double counting

            # Update velocities and positions (Verlet integration)
            for i, particle in enumerate(current_particles):
                # Update velocity
                ax = forces[i][0] / particle.mass
                ay = forces[i][1] / particle.mass
                az = forces[i][2] / particle.mass

                particle.vx += ax * params.time_step
                particle.vy += ay * params.time_step
                particle.vz += az * params.time_step

                # Update position
                particle.x += particle.vx * params.time_step
                particle.y += particle.vy * params.time_step
                particle.z += particle.vz * params.time_step

                # Apply periodic boundary conditions
                particle.x = particle.x % params.box_size
                particle.y = particle.y % params.box_size
                particle.z = particle.z % params.box_size

                # Calculate kinetic energy
                v_squared = particle.vx**2 + particle.vy**2 + particle.vz**2
                total_kinetic_energy += 0.5 * particle.mass * v_squared

            # Store energy for analysis
            total_energy = total_kinetic_energy + total_potential_energy
            energies.append(total_energy)

            # Checkpoint progress
            if step % checkpoint_interval == 0 and step > 0:
                progress = (step / params.total_steps) * 100
                emit_event(
                    "simulation.checkpoint",
                    {
                        "simulation_id": sim_id,
                        "current_step": step,
                        "progress_percent": progress,
                        "total_energy": total_energy,
                    },
                )

            # Brief yield to prevent complete CPU monopolization
            if step % 50 == 0:
                time.sleep(0.001)

        compute_time = time.time() - start_time

        # Calculate final statistics
        avg_energy = sum(energies) / len(energies) if energies else 0
        energy_variance = (
            sum((e - avg_energy) ** 2 for e in energies) / len(energies)
            if energies
            else 0
        )

        result = {
            "simulation_id": sim_id,
            "type": "molecular_dynamics",
            "particles": len(particles),
            "steps_completed": params.total_steps,
            "compute_time": compute_time,
            "average_energy": avg_energy,
            "energy_variance": energy_variance,
            "final_temperature": (2 / 3)
            * total_kinetic_energy
            / len(particles),  # Simplified
            "status": "completed",
        }

        emit_event("simulation.md.completed", result)
        return result

    except Exception as e:
        compute_time = time.time() - start_time
        error_result = {
            "simulation_id": sim_id,
            "type": "molecular_dynamics",
            "error": str(e),
            "compute_time": compute_time,
            "status": "failed",
        }

        emit_event("simulation.md.failed", error_result)
        return error_result


def climate_model_simulation(
    sim_id: str, grid_cells: List[ClimateGridCell], time_steps: int
) -> Dict:
    """Climate modeling simulation with finite difference methods"""

    emit_event(
        "simulation.climate.started",
        {
            "simulation_id": sim_id,
            "parameters": {
                "grid_cells": len(grid_cells),
                "time_steps": time_steps,
                "simulation_type": "weather_forecast",
            },
        },
    )

    start_time = time.time()

    try:
        # Initialize climate grid
        current_grid = [ClimateGridCell(**cell.__dict__) for cell in grid_cells]
        dt = 0.1  # Time step in hours
        checkpoint_interval = max(1, time_steps // 10)

        # Climate simulation main loop
        for step in range(time_steps):
            next_grid = []

            for i, cell in enumerate(current_grid):
                # Simulate atmospheric physics (simplified)

                # Temperature evolution (heat diffusion)
                neighbor_temp = 0
                neighbor_count = 0

                # Simple neighbor averaging (simplified grid connectivity)
                for j, neighbor in enumerate(current_grid):
                    if i != j:
                        lat_diff = abs(neighbor.lat - cell.lat)
                        lon_diff = abs(neighbor.lon - cell.lon)

                        if lat_diff <= 1.0 and lon_diff <= 1.0:  # Adjacent cells
                            neighbor_temp += neighbor.temperature
                            neighbor_count += 1

                if neighbor_count > 0:
                    neighbor_temp /= neighbor_count
                    # Heat diffusion
                    temp_change = 0.1 * (neighbor_temp - cell.temperature) * dt
                else:
                    temp_change = 0

                # Solar heating (simplified)
                solar_heating = 0.05 * math.sin(math.radians(cell.lat)) * dt

                # Atmospheric cooling
                cooling = -0.02 * (cell.temperature - 273.15) * dt

                new_temperature = (
                    cell.temperature + temp_change + solar_heating + cooling
                )

                # Humidity evolution
                evaporation_rate = 0.001 * max(0, cell.temperature - 273.15) * dt
                condensation_rate = 0.002 * max(0, cell.humidity - 0.8) * dt
                new_humidity = cell.humidity + evaporation_rate - condensation_rate
                new_humidity = max(0, min(1.0, new_humidity))  # Clamp to [0,1]

                # Pressure evolution (simplified barometric)
                pressure_gradient = random.uniform(-0.1, 0.1) * dt
                new_pressure = cell.pressure + pressure_gradient

                # Wind speed (simplified)
                wind_change = random.uniform(-0.5, 0.5) * dt
                new_wind_speed = max(0, cell.wind_speed + wind_change)

                # Wind direction (random walk)
                direction_change = random.uniform(-10, 10)  # degrees
                new_wind_direction = (cell.wind_direction + direction_change) % 360

                # Create new cell state
                new_cell = ClimateGridCell(
                    lat=cell.lat,
                    lon=cell.lon,
                    temperature=new_temperature,
                    humidity=new_humidity,
                    pressure=new_pressure,
                    wind_speed=new_wind_speed,
                    wind_direction=new_wind_direction,
                )

                next_grid.append(new_cell)

            current_grid = next_grid

            # Checkpoint progress
            if step % checkpoint_interval == 0 and step > 0:
                progress = (step / time_steps) * 100
                avg_temp = sum(cell.temperature for cell in current_grid) / len(
                    current_grid
                )

                emit_event(
                    "simulation.checkpoint",
                    {
                        "simulation_id": sim_id,
                        "current_step": step,
                        "progress_percent": progress,
                        "average_temperature": avg_temp - 273.15,  # Convert to Celsius
                    },
                )

            # Brief yield
            if step % 20 == 0:
                time.sleep(0.001)

        compute_time = time.time() - start_time

        # Calculate final statistics
        final_temps = [cell.temperature - 273.15 for cell in current_grid]  # Celsius
        final_humidity = [cell.humidity for cell in current_grid]
        final_pressure = [cell.pressure for cell in current_grid]

        result = {
            "simulation_id": sim_id,
            "type": "climate_model",
            "grid_cells": len(grid_cells),
            "steps_completed": time_steps,
            "compute_time": compute_time,
            "final_avg_temperature": sum(final_temps) / len(final_temps),
            "temperature_range": (min(final_temps), max(final_temps)),
            "avg_humidity": sum(final_humidity) / len(final_humidity),
            "avg_pressure": sum(final_pressure) / len(final_pressure),
            "status": "completed",
        }

        emit_event("simulation.climate.completed", result)
        return result

    except Exception as e:
        compute_time = time.time() - start_time
        error_result = {
            "simulation_id": sim_id,
            "type": "climate_model",
            "error": str(e),
            "compute_time": compute_time,
            "status": "failed",
        }

        emit_event("simulation.climate.failed", error_result)
        return error_result


def numerical_optimization(problem_id: str, problem_type: str, dimensions: int) -> Dict:
    """Solve numerical optimization problems using iterative methods"""

    start_time = time.time()

    try:
        # Initialize optimization problem
        if problem_type == "quadratic":
            # Minimize f(x) = x^T A x + b^T x + c
            target_solution = [random.uniform(-5, 5) for _ in range(dimensions)]
        elif problem_type == "rosenbrock":
            # Rosenbrock function (global minimum at (1,1,...,1))
            target_solution = [1.0] * dimensions
        else:
            target_solution = [0.0] * dimensions

        # Initialize random starting point
        x = [random.uniform(-10, 10) for _ in range(dimensions)]
        learning_rate = 0.01
        max_iterations = 2000
        tolerance = 1e-6

        errors = []

        # Gradient descent optimization
        for iteration in range(max_iterations):
            # Calculate objective function and gradient
            if problem_type == "quadratic":
                # f(x) = ||x - target||^2
                objective = sum(
                    (x[i] - target_solution[i]) ** 2 for i in range(dimensions)
                )
                gradient = [2 * (x[i] - target_solution[i]) for i in range(dimensions)]

            elif problem_type == "rosenbrock":
                # Rosenbrock function: f(x) = sum(100*(x[i+1] - x[i]^2)^2 + (1 - x[i])^2)
                objective = 0
                gradient = [0] * dimensions

                for i in range(dimensions - 1):
                    term1 = 100 * (x[i + 1] - x[i] ** 2) ** 2
                    term2 = (1 - x[i]) ** 2
                    objective += term1 + term2

                    # Gradient components
                    gradient[i] += -400 * x[i] * (x[i + 1] - x[i] ** 2) - 2 * (1 - x[i])
                    gradient[i + 1] += 200 * (x[i + 1] - x[i] ** 2)

            else:
                # Simple sphere function
                objective = sum(x[i] ** 2 for i in range(dimensions))
                gradient = [2 * x[i] for i in range(dimensions)]

            errors.append(objective)

            # Check convergence
            gradient_norm = math.sqrt(sum(g**2 for g in gradient))
            if gradient_norm < tolerance:
                converged = True
                break

            # Update solution
            for i in range(dimensions):
                x[i] -= learning_rate * gradient[i]

            # Adaptive learning rate
            if iteration > 0 and errors[-1] > errors[-2]:
                learning_rate *= 0.9  # Reduce learning rate if not improving

            # Checkpoint for long optimizations
            if iteration % 200 == 0:
                progress = (iteration / max_iterations) * 100
                emit_event(
                    "simulation.checkpoint",
                    {
                        "simulation_id": problem_id,
                        "current_step": iteration,
                        "progress_percent": progress,
                        "current_error": objective,
                    },
                )

            # Brief computational yield
            if iteration % 100 == 0:
                time.sleep(0.001)
        else:
            converged = False

        compute_time = time.time() - start_time
        final_error = errors[-1] if errors else float("inf")

        result = {
            "problem_id": problem_id,
            "problem_type": problem_type,
            "dimensions": dimensions,
            "converged": converged,
            "iterations": len(errors),
            "final_error": final_error,
            "compute_time": compute_time,
            "solution": x,
            "target": target_solution,
        }

        emit_event(f"analysis.convergence.{problem_type}", result)
        return result

    except Exception as e:
        compute_time = time.time() - start_time
        error_result = {
            "problem_id": problem_id,
            "problem_type": problem_type,
            "error": str(e),
            "compute_time": compute_time,
            "status": "failed",
        }
        return error_result


def create_particle_system(n_particles: int) -> List[Particle]:
    """Create random particle system for MD simulation"""
    particles = []
    for i in range(n_particles):
        particle = Particle(
            id=i,
            x=random.uniform(0, 10),
            y=random.uniform(0, 10),
            z=random.uniform(0, 10),
            vx=random.gauss(0, 1),
            vy=random.gauss(0, 1),
            vz=random.gauss(0, 1),
            mass=1.0,
            charge=random.choice([-1, 0, 1]),
        )
        particles.append(particle)
    return particles


def create_climate_grid(grid_size: int) -> List[ClimateGridCell]:
    """Create climate grid for weather simulation"""
    cells = []
    for i in range(grid_size):
        for j in range(grid_size):
            lat = -90 + (180 / grid_size) * i  # -90 to 90 degrees
            lon = -180 + (360 / grid_size) * j  # -180 to 180 degrees

            cell = ClimateGridCell(
                lat=lat,
                lon=lon,
                temperature=273.15 + random.uniform(-30, 40),  # Kelvin
                humidity=random.uniform(0.2, 0.9),
                pressure=1013.25 + random.uniform(-50, 50),  # hPa
                wind_speed=random.uniform(0, 30),  # m/s
                wind_direction=random.uniform(0, 360),  # degrees
            )
            cells.append(cell)
    return cells


def main():
    """Demo parallel scientific computing simulations"""
    print("🔬 Scientific Computing Simulations")
    print("=" * 50)

    with execution_session() as manager:
        # Configure for compute-intensive scientific workloads
        manager.configure().processes(4).max_threads(2).execution_mode(
            ExecutionMode.HYBRID
        ).apply()

        # 1. Molecular Dynamics Simulations
        print("\n⚛️ Running molecular dynamics simulations...")

        md_tasks = []
        for i in range(3):
            particles = create_particle_system(25 + i * 10)  # 25, 35, 45 particles
            params = SimulationParams(
                time_step=0.01,
                total_steps=200 + i * 50,  # 200, 250, 300 steps
                temperature=300.0,
                pressure=1.0,
                box_size=10.0,
            )
            md_tasks.append((f"MD_sim_{i:02d}", particles, params))

        md_start = time.time()
        md_results = manager.parallel(
            *[
                lambda sid=sid, p=p, prm=prm: molecular_dynamics_simulation(sid, p, prm)
                for sid, p, prm in md_tasks
            ]
        )
        md_duration = time.time() - md_start

        print(f"   Completed {len(md_results)} MD simulations in {md_duration:.2f}s")

        # 2. Climate Model Simulations
        print("\n🌍 Running climate model simulations...")

        climate_tasks = []
        for i in range(2):
            grid = create_climate_grid(8 + i * 2)  # 8x8, 10x10 grids
            time_steps = 150 + i * 50  # 150, 200 time steps
            climate_tasks.append((f"Climate_sim_{i:02d}", grid, time_steps))

        climate_results = manager.parallel(
            *[
                lambda sid=sid, g=g, ts=ts: climate_model_simulation(sid, g, ts)
                for sid, g, ts in climate_tasks
            ]
        )

        # 3. Numerical Optimization Problems
        print("\n📊 Running numerical optimization problems...")

        optimization_tasks = [
            ("OPT_quadratic_001", "quadratic", 5),
            ("OPT_rosenbrock_001", "rosenbrock", 3),
            ("OPT_quadratic_002", "quadratic", 8),
            ("OPT_rosenbrock_002", "rosenbrock", 4),
        ]

        opt_results = manager.parallel(
            *[
                lambda pid=pid, ptype=ptype, dims=dims: numerical_optimization(
                    pid, ptype, dims
                )
                for pid, ptype, dims in optimization_tasks
            ]
        )

        # Analyze results
        print(f"\n📊 Scientific Computing Results:")

        # MD Results
        successful_md = [r for r in md_results if r.get("status") == "completed"]
        if successful_md:
            total_particles = sum(r.get("particles", 0) for r in successful_md)
            total_steps = sum(r.get("steps_completed", 0) for r in successful_md)
            avg_time = sum(r.get("compute_time", 0) for r in successful_md) / len(
                successful_md
            )
            print(
                f"   MD Simulations: {total_particles} particles, {total_steps} total steps"
            )
            print(f"   Average MD time: {avg_time:.2f}s per simulation")

        # Climate Results
        successful_climate = [
            r for r in climate_results if r.get("status") == "completed"
        ]
        if successful_climate:
            total_cells = sum(r.get("grid_cells", 0) for r in successful_climate)
            avg_temp = sum(
                r.get("final_avg_temperature", 0) for r in successful_climate
            ) / len(successful_climate)
            print(f"   Climate Models: {total_cells} total grid cells")
            print(f"   Average final temperature: {avg_temp:.1f}°C")

        # Optimization Results
        converged_opts = [r for r in opt_results if r.get("converged", False)]
        print(
            f"   Optimization: {len(converged_opts)}/{len(opt_results)} problems converged"
        )

        if converged_opts:
            avg_iterations = sum(r.get("iterations", 0) for r in converged_opts) / len(
                converged_opts
            )
            avg_error = sum(r.get("final_error", 0) for r in converged_opts) / len(
                converged_opts
            )
            print(
                f"   Average convergence: {avg_iterations:.0f} iterations, error: {avg_error:.2e}"
            )

        # Show system performance
        metrics = manager.get_metrics()
        print(f"\n🖥️ Computational Performance:")
        print(f"   Total computations: {metrics['tasks_completed']}")
        print(f"   Scientific events: {metrics['events_published']}")
        print(f"   Process utilization: {metrics.get('process_executor', 'N/A')}")
        print(f"   System health: {manager.health_check()}")

        print(f"\n🎯 Scientific computing demonstrates:")
        print(f"   ✅ CPU-intensive parallel simulations")
        print(f"   ✅ Multi-physics modeling (MD + Climate)")
        print(f"   ✅ Iterative numerical algorithms")
        print(f"   ✅ Progress monitoring for long calculations")
        print(f"   ✅ Convergence analysis and optimization")


if __name__ == "__main__":
    main()
