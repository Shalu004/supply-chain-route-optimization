"""
Zone clustering: groups delivery stops into geographically compact zones.
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


@dataclass
class VehicleSpec:
    """Specification of a single vehicle in a heterogeneous fleet."""

    id: str
    name: str = "Vehicle"
    capacity: float = 20.0
    cost_per_km: float = 0.9
    fixed_cost: float = 50.0
    max_distance_km: float | None = None


def cluster_stops(stops: list[Stop], n_zones: int, random_state: int = 42) -> dict[int, list[Stop]]:
    """
    Group stops into `n_zones` geographically compact clusters using K-Means.
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
                far_idx = max(
                    range(len(zones[zid])),
                    key=lambda i: (zones[zid][i].lat - cy) ** 2
                    + (zones[zid][i].lon - cx) ** 2,
                )
                stop = zones[zid].pop(far_idx)

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
