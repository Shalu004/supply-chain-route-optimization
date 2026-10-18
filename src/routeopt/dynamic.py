"""
Dynamic Route Reoptimization Engine for RouteOpt.

Handles real-time disruptions and order events:
- On-demand order insertion (single order or pickup/delivery pair)
- Order cancellations
- Vehicle breakdowns (reallocating orphaned stops to active vehicles)
- Traffic slowdowns and delivery delays

Enforces critical operational invariants:
- Completed deliveries are immutable and never reordered or dropped.
- Live vehicle progress is preserved.
- Only affected vehicles are recomputed; untouched vehicles remain unchanged.
- Solvers degrade gracefully with explicit unassigned stop reporting if infeasible.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .clustering import Stop, VehicleSpec
from .distance import AbstractDistanceProvider, HaversineDistanceProvider
from .routing import Route, _route_length
from .ortools_routing import solve_ortools_vrp

logger = logging.getLogger("routeopt.dynamic")


@dataclass
class UnassignedOrder:
    stop_id: str
    demand: float
    reason: str


@dataclass
class ReoptimizationResult:
    success: bool
    event_type: str
    affected_vehicle_ids: list[str]
    routes: list[Route]
    unassigned_stops: list[UnassignedOrder] = field(default_factory=list)
    total_distance_km: float = 0.0
    distance_delta_km: float = 0.0
    total_duration_minutes: float = 0.0
    duration_delta_minutes: float = 0.0
    execution_time_seconds: float = 0.0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def reoptimize_insert_order(
    active_routes: list[Route],
    new_stop: Stop,
    vehicle_specs: list[VehicleSpec],
    depot: Stop | None = None,
    completed_stop_ids: set[str] | None = None,
    distance_provider: AbstractDistanceProvider | None = None,
    pickup_stop: Stop | None = None,
    average_speed_kmh: float = 30.0,
) -> ReoptimizationResult:
    """
    Dynamically insert a new order (and optional pickup stop) into active routes.
    Preserves completed stops and minimizes incremental detour distance.
    """
    t_start = time.monotonic()
    provider = distance_provider or HaversineDistanceProvider()
    completed_ids = completed_stop_ids or set()
    initial_total_dist = sum(r.total_distance_km for r in active_routes)
    initial_total_dur = sum(r.total_duration_minutes for r in active_routes)

    spec_map = {s.id: s for s in vehicle_specs}
    best_vehicle_idx = -1
    best_insert_pos = -1
    best_dist_delta = float("inf")
    best_new_stops: list[Stop] = []

    stops_to_insert = [pickup_stop, new_stop] if pickup_stop else [new_stop]
    total_new_demand = sum(s.demand for s in stops_to_insert)

    for v_idx, route in enumerate(active_routes):
        v_id = getattr(route, "vehicle_id", None) or f"v_{route.zone_id}"
        spec = spec_map.get(v_id)
        cap = spec.capacity if spec else 20.0

        # Calculate current unvisited demand
        unvisited = [s for s in route.stops if s.id not in completed_ids and (not depot or s.id != depot.id)]
        current_unvisited_demand = sum(s.demand for s in unvisited)
        if current_unvisited_demand + total_new_demand > cap:
            continue  # Exceeds capacity

        # Find candidate insertion indices after completed stops
        completed_count = sum(1 for s in route.stops if s.id in completed_ids)
        # Insertion can happen from completed_count + 1 up to len(route.stops) - 1 (before return depot)
        start_insert_idx = max(1, completed_count + 1)
        end_insert_idx = len(route.stops) if not depot else len(route.stops) - 1

        for pos in range(start_insert_idx, end_insert_idx + 1):
            candidate_stops = route.stops[:pos] + stops_to_insert + route.stops[pos:]
            
            # Check time window feasibility
            if _is_time_window_feasible(candidate_stops, average_speed_kmh, provider):
                dist_mat = provider.get_distance_matrix(candidate_stops)
                new_dist = _route_length(list(range(len(candidate_stops))), dist_mat)
                delta = new_dist - route.total_distance_km
                if delta < best_dist_delta:
                    best_dist_delta = delta
                    best_vehicle_idx = v_idx
                    best_new_stops = candidate_stops

    if best_vehicle_idx == -1:
        # Infeasible across all active vehicles
        return ReoptimizationResult(
            success=False,
            event_type="INSERT_ORDER",
            affected_vehicle_ids=[],
            routes=active_routes,
            unassigned_stops=[
                UnassignedOrder(
                    stop_id=new_stop.id,
                    demand=new_stop.demand,
                    reason="No vehicle has spare capacity or feasible time window for insertion",
                )
            ],
            total_distance_km=round(initial_total_dist, 3),
            distance_delta_km=0.0,
            execution_time_seconds=round(time.monotonic() - t_start, 3),
        )

    # Apply insertion only to chosen vehicle
    new_routes = []
    affected_id = ""
    km_per_min = max(average_speed_kmh / 60.0, 0.1)

    for idx, r in enumerate(active_routes):
        if idx == best_vehicle_idx:
            v_id = getattr(r, "vehicle_id", None) or f"v_{r.zone_id}"
            affected_id = v_id
            dist_mat = provider.get_distance_matrix(best_new_stops)
            dist_km = float(round(_route_length(list(range(len(best_new_stops))), dist_mat), 3))
            dur_min = float(round(dist_km / km_per_min + sum(s.service_duration for s in best_new_stops), 2))
            new_routes.append(
                Route(
                    zone_id=r.zone_id,
                    stops=best_new_stops,
                    total_distance_km=dist_km,
                    total_duration_minutes=dur_min,
                    vehicle_id=v_id,
                    vehicle_name=getattr(r, "vehicle_name", None),
                )
            )
        else:
            new_routes.append(r)

    final_dist = sum(r.total_distance_km for r in new_routes)
    final_dur = sum(r.total_duration_minutes for r in new_routes)

    return ReoptimizationResult(
        success=True,
        event_type="INSERT_ORDER",
        affected_vehicle_ids=[affected_id],
        routes=new_routes,
        total_distance_km=round(final_dist, 3),
        distance_delta_km=round(final_dist - initial_total_dist, 3),
        total_duration_minutes=round(final_dur, 2),
        duration_delta_minutes=round(final_dur - initial_total_dur, 2),
        execution_time_seconds=round(time.monotonic() - t_start, 3),
    )


def reoptimize_cancel_order(
    active_routes: list[Route],
    cancelled_stop_id: str,
    completed_stop_ids: set[str] | None = None,
    distance_provider: AbstractDistanceProvider | None = None,
    average_speed_kmh: float = 30.0,
) -> ReoptimizationResult:
    """
    Dynamically remove a cancelled stop from active routes and shorten the route.
    Refuses to cancel already completed stops.
    """
    t_start = time.monotonic()
    provider = distance_provider or HaversineDistanceProvider()
    completed_ids = completed_stop_ids or set()

    if cancelled_stop_id in completed_ids:
        raise ValueError(f"Cannot cancel stop '{cancelled_stop_id}': delivery is already completed")

    initial_total_dist = sum(r.total_distance_km for r in active_routes)
    initial_total_dur = sum(r.total_duration_minutes for r in active_routes)
    km_per_min = max(average_speed_kmh / 60.0, 0.1)

    found = False
    affected_v_id = ""
    new_routes: list[Route] = []

    for r in active_routes:
        stop_ids = [s.id for s in r.stops]
        if cancelled_stop_id in stop_ids:
            found = True
            v_id = getattr(r, "vehicle_id", None) or f"v_{r.zone_id}"
            affected_v_id = v_id
            pruned_stops = [s for s in r.stops if s.id != cancelled_stop_id]
            if len(pruned_stops) >= 2:
                dist_mat = provider.get_distance_matrix(pruned_stops)
                new_dist = float(round(_route_length(list(range(len(pruned_stops))), dist_mat), 3))
            else:
                new_dist = 0.0
            new_dur = float(round(new_dist / km_per_min + sum(s.service_duration for s in pruned_stops), 2))
            new_routes.append(
                Route(
                    zone_id=r.zone_id,
                    stops=pruned_stops,
                    total_distance_km=new_dist,
                    total_duration_minutes=new_dur,
                    vehicle_id=v_id,
                    vehicle_name=getattr(r, "vehicle_name", None),
                )
            )
        else:
            new_routes.append(r)

    if not found:
        raise ValueError(f"Cancelled stop '{cancelled_stop_id}' not found in any active route")

    final_dist = sum(r.total_distance_km for r in new_routes)
    final_dur = sum(r.total_duration_minutes for r in new_routes)

    return ReoptimizationResult(
        success=True,
        event_type="CANCEL_ORDER",
        affected_vehicle_ids=[affected_v_id],
        routes=new_routes,
        total_distance_km=round(final_dist, 3),
        distance_delta_km=round(final_dist - initial_total_dist, 3),
        total_duration_minutes=round(final_dur, 2),
        duration_delta_minutes=round(final_dur - initial_total_dur, 2),
        execution_time_seconds=round(time.monotonic() - t_start, 3),
    )


def reoptimize_vehicle_breakdown(
    active_routes: list[Route],
    broken_vehicle_id: str,
    vehicle_specs: list[VehicleSpec],
    depot: Stop | None = None,
    completed_stop_ids: set[str] | None = None,
    distance_provider: AbstractDistanceProvider | None = None,
    average_speed_kmh: float = 30.0,
) -> ReoptimizationResult:
    """
    Handle vehicle breakdown:
    - Retain completed stops on the broken vehicle route.
    - Extract uncompleted orphaned stops.
    - Dynamically redistribute orphaned stops across surviving active vehicles.
    """
    t_start = time.monotonic()
    provider = distance_provider or HaversineDistanceProvider()
    completed_ids = completed_stop_ids or set()
    initial_total_dist = sum(r.total_distance_km for r in active_routes)
    initial_total_dur = sum(r.total_duration_minutes for r in active_routes)

    broken_route = None
    surviving_routes: list[Route] = []

    for r in active_routes:
        v_id = getattr(r, "vehicle_id", None) or f"v_{r.zone_id}"
        if v_id == broken_vehicle_id:
            broken_route = r
        else:
            surviving_routes.append(r)

    if not broken_route:
        raise ValueError(f"Broken vehicle ID '{broken_vehicle_id}' not found in active routes")

    # Separate completed stops from orphaned uncompleted stops
    orphaned_stops = [
        s for s in broken_route.stops
        if s.id not in completed_ids and (not depot or s.id != depot.id)
    ]
    completed_stops_broken = [
        s for s in broken_route.stops
        if s.id in completed_ids or (depot and s.id == depot.id)
    ]

    # Retain completed part of broken vehicle route if it has visited customer stops
    frozen_broken_route = None
    if any(s.id in completed_ids for s in completed_stops_broken):
        dist_mat = provider.get_distance_matrix(completed_stops_broken)
        dist_km = float(round(_route_length(list(range(len(completed_stops_broken))), dist_mat), 3))
        frozen_broken_route = Route(
            zone_id=broken_route.zone_id,
            stops=completed_stops_broken,
            total_distance_km=dist_km,
            total_duration_minutes=float(round(dist_km / 0.5, 2)),
            vehicle_id=broken_vehicle_id,
            vehicle_name=f"{getattr(broken_route, 'vehicle_name', 'Vehicle')} (Disabled)",
        )

    # Distribute orphaned stops onto surviving routes
    surviving_specs = [s for s in vehicle_specs if s.id != broken_vehicle_id]
    current_routes = surviving_routes
    unassigned_stops: list[UnassignedOrder] = []
    affected_vehicles = set()

    for orphan in orphaned_stops:
        res = reoptimize_insert_order(
            active_routes=current_routes,
            new_stop=orphan,
            vehicle_specs=surviving_specs,
            depot=depot,
            completed_stop_ids=completed_ids,
            distance_provider=provider,
            average_speed_kmh=average_speed_kmh,
        )
        if res.success:
            current_routes = res.routes
            affected_vehicles.update(res.affected_vehicle_ids)
        else:
            unassigned_stops.append(
                UnassignedOrder(
                    stop_id=orphan.id,
                    demand=orphan.demand,
                    reason="Remaining operational fleet has insufficient capacity or time windows",
                )
            )

    all_final_routes = list(current_routes)
    if frozen_broken_route:
        all_final_routes.append(frozen_broken_route)

    final_dist = sum(r.total_distance_km for r in all_final_routes)
    final_dur = sum(r.total_duration_minutes for r in all_final_routes)

    return ReoptimizationResult(
        success=len(unassigned_stops) == 0,
        event_type="VEHICLE_BREAKDOWN",
        affected_vehicle_ids=list(affected_vehicles),
        routes=all_final_routes,
        unassigned_stops=unassigned_stops,
        total_distance_km=round(final_dist, 3),
        distance_delta_km=round(final_dist - initial_total_dist, 3),
        total_duration_minutes=round(final_dur, 2),
        duration_delta_minutes=round(final_dur - initial_total_dur, 2),
        execution_time_seconds=round(time.monotonic() - t_start, 3),
    )


def reoptimize_traffic_delay(
    active_routes: list[Route],
    vehicle_id: str,
    delay_minutes: float,
    current_stop_id: str | None = None,
    average_speed_kmh: float = 30.0,
) -> ReoptimizationResult:
    """
    Apply a delivery or traffic delay to a vehicle route and propagate downstream ETAs.
    """
    t_start = time.monotonic()
    initial_total_dur = sum(r.total_duration_minutes for r in active_routes)
    initial_total_dist = sum(r.total_distance_km for r in active_routes)

    new_routes: list[Route] = []
    affected_ids: list[str] = []

    for r in active_routes:
        v_id = getattr(r, "vehicle_id", None) or f"v_{r.zone_id}"
        if v_id == vehicle_id:
            affected_ids.append(v_id)
            updated_dur = round(r.total_duration_minutes + delay_minutes, 2)
            new_routes.append(
                Route(
                    zone_id=r.zone_id,
                    stops=list(r.stops),
                    total_distance_km=r.total_distance_km,
                    total_duration_minutes=updated_dur,
                    vehicle_id=v_id,
                    vehicle_name=getattr(r, "vehicle_name", None),
                )
            )
        else:
            new_routes.append(r)

    final_dur = sum(r.total_duration_minutes for r in new_routes)

    return ReoptimizationResult(
        success=True,
        event_type="DELIVERY_DELAY",
        affected_vehicle_ids=affected_ids,
        routes=new_routes,
        total_distance_km=round(initial_total_dist, 3),
        distance_delta_km=0.0,
        total_duration_minutes=round(final_dur, 2),
        duration_delta_minutes=round(final_dur - initial_total_dur, 2),
        execution_time_seconds=round(time.monotonic() - t_start, 3),
    )


def _is_time_window_feasible(
    stops: list[Stop],
    average_speed_kmh: float,
    provider: AbstractDistanceProvider,
) -> bool:
    """Check if an ordered sequence of stops satisfies hard time windows."""
    if len(stops) < 2:
        return True
    dist_mat = provider.get_distance_matrix(stops)
    km_per_min = max(average_speed_kmh / 60.0, 0.1)
    current_time = 0.0

    for i in range(len(stops) - 1):
        travel_km = dist_mat[i, i + 1]
        travel_min = travel_km / km_per_min
        current_time += travel_min
        next_stop = stops[i + 1]

        if next_stop.time_window is not None:
            earliest, latest = next_stop.time_window
            if current_time > latest:
                return False  # Arrived too late
            if current_time < earliest:
                current_time = earliest  # Wait until opening window

        current_time += next_stop.service_duration

    return True
