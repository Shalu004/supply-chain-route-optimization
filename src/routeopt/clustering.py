"""
Zone clustering: groups delivery stops into geographically compact zones.

Each zone is later handed to the routing engine as an independent
Vehicle Routing / TSP sub-problem. Clustering first, then routing,
is standard practice in logistics optimization -- it keeps each
sub-problem small enough to solve fast and lets each cluster map
cleanly to a single vehicle.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.cluster import KMeans


@dataclass
class Stop:
    """A single delivery stop."""

    id: str
    lat: float
    lon: float
    demand: float = 1.0  # e.g. package count or weight; used for capacity checks


def cluster_stops(stops: list[Stop], n_zones: int, random_state: int = 42) -> dict[int, list[Stop]]:
    """
    Group stops into `n_zones` geographically compact clusters using K-Means.

    K-Means on raw lat/lon is a reasonable approximation for city-scale
    distances. For very large service areas (spanning many degrees of
    latitude), swap the coordinate space for a projected CRS first --
    see `to_projected_xy()` below.

    Args:
        stops: delivery stops to cluster.
        n_zones: number of zones (typically = number of available vehicles).
        random_state: for reproducible clustering runs.

    Returns:
        Mapping of zone_id -> list of Stop objects in that zone.

    Raises:
        ValueError: if n_zones is larger than the number of stops, or stops is empty.
    """
    if not stops:
        raise ValueError("cluster_stops() received an empty stop list")
    if n_zones < 1:
        raise ValueError("n_zones must be >= 1")
    if n_zones > len(stops):
        raise ValueError(
            f"n_zones ({n_zones}) cannot exceed number of stops ({len(stops)})"
        )

    coords = np.array([[s.lat, s.lon] for s in stops])

    if n_zones == 1:
        return {0: list(stops)}

    model = KMeans(n_clusters=n_zones, random_state=random_state, n_init=10)
    labels = model.fit_predict(coords)

    zones: dict[int, list[Stop]] = {i: [] for i in range(n_zones)}
    for stop, label in zip(stops, labels):
        zones[int(label)].append(stop)

    return zones


def balance_zones_by_capacity(
    zones: dict[int, list[Stop]], vehicle_capacity: float
) -> dict[int, list[Stop]]:
    """
    Rebalance clusters that exceed a vehicle's capacity by peeling off the
    stops farthest from the zone centroid and reassigning them to the
    nearest zone with spare capacity.

    This is a greedy heuristic, not an exact solver -- adequate for keeping
    demos and small-to-mid fleets within capacity. For hard capacity
    guarantees at scale, this responsibility should move into the VRP
    solver itself (OR-Tools supports capacity constraints natively).
    """
    zones = {k: list(v) for k, v in zones.items()}  # shallow copy

    def zone_demand(zid: int) -> float:
        return sum(s.demand for s in zones[zid])

    def centroid(zid: int) -> tuple[float, float]:
        pts = zones[zid]
        return (
            sum(s.lat for s in pts) / len(pts),
            sum(s.lon for s in pts) / len(pts),
        )

    changed = True
    guard = 0
    while changed and guard < 1000:
        changed = False
        guard += 1
        for zid in list(zones.keys()):
            while zone_demand(zid) > vehicle_capacity and len(zones[zid]) > 1:
                cy, cx = centroid(zid)
                # farthest stop from this zone's centroid
                far_idx = max(
                    range(len(zones[zid])),
                    key=lambda i: (zones[zid][i].lat - cy) ** 2
                    + (zones[zid][i].lon - cx) ** 2,
                )
                stop = zones[zid].pop(far_idx)

                # find nearest zone with spare capacity
                candidates = [
                    z for z in zones if z != zid and zone_demand(z) + stop.demand <= vehicle_capacity
                ]
                if not candidates:
                    zones[zid].append(stop)  # can't move it, put back
                    break

                target = min(
                    candidates,
                    key=lambda z: (centroid(z)[0] - stop.lat) ** 2
                    + (centroid(z)[1] - stop.lon) ** 2,
                )
                zones[target].append(stop)
                changed = True

    return zones
