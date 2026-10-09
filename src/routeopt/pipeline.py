"""
Top-level orchestration: raw stops -> clustered zones / OR-Tools VRP -> optimized routes
-> cost comparison against a naive baseline.

This is the module the API layer calls. Framework-agnostic and portable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .clustering import Stop, VehicleSpec, balance_zones_by_capacity, cluster_stops
from .distance import AbstractDistanceProvider, get_distance_provider
from .routing import Route, solve_all_zones

logger = logging.getLogger("routeopt.pipeline")


@dataclass
class CostModel:
    """Simple linear cost model. Swap in real fleet economics as needed."""

    cost_per_km: float = 0.9  # e.g. USD per km (fuel + driver time amortized)
    cost_per_vehicle: float = 50.0  # fixed dispatch cost per vehicle used


@dataclass
class OptimizationResult:
    routes: list[Route]
    total_distance_km: float
    total_cost: float
    vehicles_used: int
    baseline_distance_km: float
    baseline_cost: float
    cost_reduction_pct: float
    solver_used: str = "heuristic"
    distance_provider_used: str = "haversine"


def _baseline(
    stops: list[Stop],
    n_vehicles: int,
    depot: Stop | None,
    distance_provider: AbstractDistanceProvider | None = None,
) -> tuple[float, int]:
    """
    Naive baseline: the SAME fleet size as the optimized run, but stops are
    split into contiguous chunks in as-received order (no clustering) and
    visited in that order with no route optimization.

    Returns:
        (total_distance_km, vehicles_used) for the naive baseline.
    """
    from .distance import HaversineDistanceProvider
    from .routing import _route_length

    provider = distance_provider or HaversineDistanceProvider()
    n_chunks = min(n_vehicles, len(stops))
    chunk_size = -(-len(stops) // n_chunks)  # ceil division

    total_distance = 0.0
    vehicles_used = 0

    for i in range(0, len(stops), chunk_size):
        chunk = stops[i : i + chunk_size]
        if not chunk:
            continue
        vehicles_used += 1
        pts = [depot] + chunk if depot else chunk
        if len(pts) < 2:
            continue
        dist = provider.get_distance_matrix(pts)
        total_distance += _route_length(list(range(len(pts))), dist)

    return total_distance, vehicles_used


def run_optimization(
    stops: list[Stop],
    n_vehicles: int,
    vehicle_capacity: float,
    depot: Stop | None = None,
    cost_model: CostModel | None = None,
    solver_type: str = "ortools",
    distance_provider: str = "haversine",
    vehicle_specs: list[VehicleSpec] | None = None,
    max_route_distance_km: float | None = None,
    use_cache: bool = True,
    average_speed_kmh: float = 30.0,
) -> OptimizationResult:
    """
    Full optimization pipeline.

    Supports Google OR-Tools VRP solver ("ortools") and fallback K-Means + 2-Opt ("heuristic"),
    heterogeneous vehicle fleet specs, max route distance limits, and pluggable distance matrix providers.
    """
    cost_model = cost_model or CostModel()
    dist_provider_obj = get_distance_provider(distance_provider, use_cache=use_cache)
    routes: list[Route] = []

    if solver_type not in ("ortools", "heuristic"):
        logger.warning(
            "Unknown solver_type '%s'; defaulting to 'heuristic'.", solver_type
        )
        actual_solver = "heuristic"
    else:
        actual_solver = solver_type

    effective_n_vehicles = len(vehicle_specs) if vehicle_specs else n_vehicles

    has_time_windows = any(s.time_window is not None or s.soft_time_window is not None for s in stops)
    has_pdp = any(s.pickup_stop_id is not None for s in stops)

    if actual_solver == "ortools":
        try:
            from .ortools_routing import solve_ortools_vrp

            routes = solve_ortools_vrp(
                stops=stops,
                n_vehicles=effective_n_vehicles,
                vehicle_capacity=vehicle_capacity,
                depot=depot,
                distance_provider=dist_provider_obj,
                vehicle_specs=vehicle_specs,
                max_route_distance_km=max_route_distance_km,
                average_speed_kmh=average_speed_kmh,
            )
            actual_solver = "ortools"
        except Exception as e:
            if has_time_windows or has_pdp:
                logger.error(
                    "OR-Tools solver failed to find a feasible solution under constraints (VRPTW/PDP): %s", e
                )
                raise ValueError(
                    f"Infeasible routing request: OR-Tools could not satisfy specified constraints (time windows or pickup/delivery precedence) with available fleet ({e})"
                )
            logger.warning(
                "OR-Tools solver failed or infeasible (%s); falling back to heuristic solver.",
                e,
            )
            actual_solver = "heuristic (fallback)"
            routes = []

    if not routes or actual_solver.startswith("heuristic"):
        zones = cluster_stops(stops, n_zones=effective_n_vehicles)
        zones = balance_zones_by_capacity(zones, vehicle_capacity)
        routes = solve_all_zones(zones, depot=depot, distance_provider=dist_provider_obj)
        if actual_solver == "ortools":
            actual_solver = "heuristic"

    total_distance = sum(r.total_distance_km for r in routes)
    vehicles_used = sum(1 for r in routes if r.stops)
    total_cost = total_distance * cost_model.cost_per_km + vehicles_used * cost_model.cost_per_vehicle

    baseline_distance, baseline_vehicles = _baseline(
        stops, effective_n_vehicles, depot, distance_provider=dist_provider_obj
    )
    baseline_cost = (
        baseline_distance * cost_model.cost_per_km
        + baseline_vehicles * cost_model.cost_per_vehicle
    )

    reduction_pct = (
        0.0 if baseline_cost == 0 else round((1 - total_cost / baseline_cost) * 100, 2)
    )

    return OptimizationResult(
        routes=routes,
        total_distance_km=float(round(total_distance, 3)),
        total_cost=float(round(total_cost, 2)),
        vehicles_used=int(vehicles_used),
        baseline_distance_km=float(round(baseline_distance, 3)),
        baseline_cost=float(round(baseline_cost, 2)),
        cost_reduction_pct=float(reduction_pct),
        solver_used=actual_solver,
        distance_provider_used=distance_provider.lower().strip(),
    )
