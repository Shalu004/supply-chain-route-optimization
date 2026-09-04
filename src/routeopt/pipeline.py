"""
Top-level orchestration: raw stops -> clustered zones -> optimized routes
-> cost comparison against a naive baseline.

This is the module the API layer calls. Nothing here should import
Flask/FastAPI -- keeping the engine framework-agnostic is what makes it
portable to a job queue (Celery/RQ) later without rewriting it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .clustering import Stop, balance_zones_by_capacity, cluster_stops
from .routing import Route, solve_all_zones


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


def _baseline(
    stops: list[Stop], n_vehicles: int, depot: Stop | None
) -> tuple[float, int]:
    """
    Naive baseline: the SAME fleet size as the optimized run, but stops are
    split into contiguous chunks in as-received order (no clustering) and
    visited in that order with no route optimization (no 2-opt).

    Using the same vehicle count is essential for an honest comparison --
    if the baseline used fewer vehicles, its lower fixed dispatch cost
    could mask genuinely worse routing, and the "% cost reduction" figure
    would be measuring fleet size instead of routing quality.

    Returns:
        (total_distance_km, vehicles_used) for the naive baseline.
    """
    from .routing import _haversine_matrix, _route_length

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
        dist = _haversine_matrix(pts)
        total_distance += _route_length(list(range(len(pts))), dist)

    return total_distance, vehicles_used


def run_optimization(
    stops: list[Stop],
    n_vehicles: int,
    vehicle_capacity: float,
    depot: Stop | None = None,
    cost_model: CostModel | None = None,
) -> OptimizationResult:
    """
    Full pipeline: cluster stops into `n_vehicles` zones, optimize each
    zone's route, and compare total cost against a naive single-route
    baseline.

    Args:
        stops: all delivery stops for this run.
        n_vehicles: number of vehicles / zones to split stops into.
        vehicle_capacity: max demand (packages/weight) per vehicle.
        depot: optional shared start/end point for every route.
        cost_model: cost coefficients; defaults to CostModel().

    Returns:
        OptimizationResult with routes, costs, and % improvement over baseline.
    """
    cost_model = cost_model or CostModel()

    zones = cluster_stops(stops, n_zones=n_vehicles)
    zones = balance_zones_by_capacity(zones, vehicle_capacity)
    routes = solve_all_zones(zones, depot=depot)

    total_distance = sum(r.total_distance_km for r in routes)
    vehicles_used = sum(1 for r in routes if r.stops)
    total_cost = total_distance * cost_model.cost_per_km + vehicles_used * cost_model.cost_per_vehicle

    baseline_distance, baseline_vehicles = _baseline(stops, n_vehicles, depot)
    baseline_cost = (
        baseline_distance * cost_model.cost_per_km
        + baseline_vehicles * cost_model.cost_per_vehicle
    )

    reduction_pct = (
        0.0 if baseline_cost == 0 else round((1 - total_cost / baseline_cost) * 100, 2)
    )

    return OptimizationResult(
        routes=routes,
        total_distance_km=round(total_distance, 3),
        total_cost=round(total_cost, 2),
        vehicles_used=vehicles_used,
        baseline_distance_km=round(baseline_distance, 3),
        baseline_cost=round(baseline_cost, 2),
        cost_reduction_pct=reduction_pct,
    )
