"""
Route sequencing: given a zone's stops, decide the visiting order that
minimizes total travel distance (a per-zone Traveling Salesman Problem).

Production note
----------------
This module implements a nearest-neighbor + 2-opt heuristic using only
numpy/scipy, because Google OR-Tools isn't available in this environment.
OR-Tools' `RoutingModel` is the industry-standard choice for real
deployments -- it natively supports multi-vehicle capacity constraints,
time windows, and pickup/delivery pairing, and scales better on large
instances. Swapping this module for an OR-Tools-backed implementation
is a drop-in replacement: keep the same `solve_route(stops) -> Route`
interface and nothing upstream (clustering, API, dashboard) needs to
change. See `routing_ortools.py.stub` for the intended production
signature.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

from .clustering import Stop


@dataclass
class Route:
    """An ordered sequence of stops for a single vehicle."""

    zone_id: int
    stops: list[Stop]
    total_distance_km: float = 0.0


EARTH_RADIUS_KM = 6371.0


def _haversine_matrix(stops: list[Stop]) -> np.ndarray:
    """Pairwise great-circle distance matrix (km) between stops."""
    lat = np.radians(np.array([s.lat for s in stops]))
    lon = np.radians(np.array([s.lon for s in stops]))

    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]

    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2.0) ** 2
    )
    c = 2 * np.arcsin(np.clip(np.sqrt(a), -1, 1))
    return EARTH_RADIUS_KM * c


def _nearest_neighbor_order(dist: np.ndarray) -> list[int]:
    """Greedy construction: repeatedly visit the closest unvisited stop."""
    n = dist.shape[0]
    visited = [0]
    remaining = set(range(1, n))
    while remaining:
        last = visited[-1]
        nxt = min(remaining, key=lambda j: dist[last, j])
        visited.append(nxt)
        remaining.remove(nxt)
    return visited


def _route_length(order: list[int], dist: np.ndarray) -> float:
    return sum(dist[order[i], order[i + 1]] for i in range(len(order) - 1))


def _two_opt(order: list[int], dist: np.ndarray, max_iterations: int = 200) -> list[int]:
    """
    Local-search refinement: repeatedly reverse a segment of the route if
    doing so shortens total distance. Standard TSP improvement heuristic.
    """
    best = order[:]
    best_len = _route_length(best, dist)
    improved = True
    iterations = 0

    while improved and iterations < max_iterations:
        improved = False
        iterations += 1
        for i, j in combinations(range(1, len(best) - 1), 2):
            candidate = best[:i] + best[i : j + 1][::-1] + best[j + 1 :]
            candidate_len = _route_length(candidate, dist)
            if candidate_len < best_len - 1e-9:
                best, best_len = candidate, candidate_len
                improved = True
    return best


def solve_route(zone_id: int, stops: list[Stop], depot: Stop | None = None) -> Route:
    """
    Compute the shortest visiting order for a single zone's stops.

    Args:
        zone_id: identifier of the zone this route belongs to.
        stops: stops to visit, in any order.
        depot: optional fixed start/end point (e.g. the warehouse). If
            given, it is prepended to the sequence and the route returns
            to it.

    Returns:
        A Route with stops in optimized order and total distance in km.
    """
    if not stops:
        return Route(zone_id=zone_id, stops=[], total_distance_km=0.0)

    ordered_stops = [depot] + stops if depot else list(stops)

    if len(ordered_stops) < 3:
        dist = _haversine_matrix(ordered_stops)
        total = _route_length(list(range(len(ordered_stops))), dist)
        return Route(zone_id=zone_id, stops=ordered_stops, total_distance_km=float(round(total, 3)))

    dist = _haversine_matrix(ordered_stops)
    order = _nearest_neighbor_order(dist)
    order = _two_opt(order, dist)

    final_stops = [ordered_stops[i] for i in order]
    total = _route_length(order, dist)

    return Route(zone_id=zone_id, stops=final_stops, total_distance_km=float(round(total, 3)))


def solve_all_zones(zones: dict[int, list[Stop]], depot: Stop | None = None) -> list[Route]:
    """Solve routing independently for every zone. Trivially parallelizable."""
    return [solve_route(zid, stops, depot) for zid, stops in zones.items()]
