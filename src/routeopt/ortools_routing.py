"""
Google OR-Tools solver integration for Vehicle Routing Problem (VRP / CVRP / VRPTW / PDP).

Provides exact / metaheuristic VRP solving with vehicle capacity constraints,
heterogeneous fleet capacities, max route distance limits, max route duration / working time,
earliest departure and latest return shift availability, distinct start/end depots,
time windows (VRPTW), pickup & delivery constraints (PDP), and native multi-vehicle routing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
import numpy as np

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .clustering import Stop, VehicleSpec
from .distance import AbstractDistanceProvider, HaversineDistanceProvider
from .routing import Route, _route_length

logger = logging.getLogger("routeopt.ortools")


def solve_ortools_vrp(
    stops: list[Stop],
    n_vehicles: int,
    vehicle_capacity: float,
    depot: Stop | None = None,
    time_limit_seconds: int = 3,
    distance_provider: AbstractDistanceProvider | None = None,
    vehicle_specs: list[VehicleSpec] | None = None,
    max_route_distance_km: float | None = None,
    max_route_duration_minutes: float | None = None,
    average_speed_kmh: float = 30.0,
) -> list[Route]:
    """
    Solve the Vehicle Routing Problem (CVRP / VRPTW / PDP) using Google OR-Tools.

    Args:
        stops: list of delivery stops to visit.
        n_vehicles: number of available vehicles.
        vehicle_capacity: default maximum demand capacity per vehicle.
        depot: optional default warehouse depot location.
        time_limit_seconds: maximum execution time limit for the solver.
        distance_provider: distance matrix provider (defaults to Haversine).
        vehicle_specs: optional heterogeneous vehicle specifications list.
        max_route_distance_km: optional maximum route distance constraint.
        max_route_duration_minutes: optional maximum route duration / working time.
        average_speed_kmh: assumed average fleet speed in km/h for travel time calculation.

    Returns:
        list of Route objects (one per active vehicle).

    Raises:
        ValueError: if stops is empty, n_vehicles < 1, or OR-Tools cannot find a feasible solution.
    """
    if not stops:
        return []

    if n_vehicles < 1:
        raise ValueError("n_vehicles must be >= 1")

    provider = distance_provider or HaversineDistanceProvider()

    # Determine vehicle count and active specifications
    if vehicle_specs:
        num_vehicles = len(vehicle_specs)
        active_specs = list(vehicle_specs)
    else:
        num_vehicles = n_vehicles
        active_specs = [
            VehicleSpec(id=f"v_{i}", capacity=vehicle_capacity)
            for i in range(num_vehicles)
        ]

    # Gather all unique depot locations (default depot + per-vehicle start/end depots)
    depot_locations: list[Stop] = []
    if depot is not None:
        depot_locations.append(depot)

    for spec in active_specs:
        if spec.start_depot and not any(d.id == spec.start_depot.id for d in depot_locations):
            depot_locations.append(spec.start_depot)
        if spec.end_depot and not any(d.id == spec.end_depot.id for d in depot_locations):
            depot_locations.append(spec.end_depot)

    if not depot_locations:
        all_locations = list(stops)
        depot_ids: set[str] = set()
        starts = [0] * num_vehicles
        ends = [0] * num_vehicles
    else:
        depot_ids = {d.id for d in depot_locations}
        all_locations = list(depot_locations) + list(stops)
        depot_id_to_idx = {d.id: idx for idx, d in enumerate(depot_locations)}
        default_idx = 0

        starts = []
        ends = []
        for spec in active_specs:
            s_idx = depot_id_to_idx.get(spec.start_depot.id, default_idx) if spec.start_depot else default_idx
            e_idx = depot_id_to_idx.get(spec.end_depot.id, s_idx) if spec.end_depot else (
                default_idx if not spec.start_depot else s_idx
            )
            starts.append(s_idx)
            ends.append(e_idx)

    num_locations = len(all_locations)
    stop_id_to_node = {s.id: idx for idx, s in enumerate(all_locations)}

    # Distance matrix (in integer meters for arc cost)
    dist_matrix_km = provider.get_distance_matrix(all_locations)
    dist_matrix_meters = (dist_matrix_km * 1000.0).astype(int)

    # Scale demands and vehicle capacities
    SCALE = 100
    demands = [
        0 if loc.id in depot_ids else int(round(loc.demand * SCALE))
        for loc in all_locations
    ]
    vehicle_capacities = [int(round(spec.capacity * SCALE)) for spec in active_specs]

    # Initialize RoutingIndexManager and RoutingModel
    if all(s == 0 for s in starts) and all(e == 0 for e in ends):
        manager = pywrapcp.RoutingIndexManager(num_locations, num_vehicles, 0)
    else:
        manager = pywrapcp.RoutingIndexManager(num_locations, num_vehicles, starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    # Arc cost callback
    def distance_callback(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(dist_matrix_meters[from_node, to_node])

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Vehicle Capacity Dimension
    def demand_callback(from_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        return demands[from_node]

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,  # null capacity slack
        vehicle_capacities,
        True,
        "Capacity",
    )

    # Distance Limit Dimension
    has_dist_limit = max_route_distance_km is not None or any(s.max_distance_km for s in active_specs)
    if has_dist_limit:
        MAX_DIST_METERS = 10000000  # 10,000 km
        routing.AddDimension(
            transit_callback_index,
            0,
            MAX_DIST_METERS,
            True,
            "Distance",
        )
        dist_dimension = routing.GetDimensionOrDie("Distance")
        for v_idx, spec in enumerate(active_specs):
            v_max = spec.max_distance_km or max_route_distance_km
            if v_max is not None:
                dist_dimension.CumulVar(routing.End(v_idx)).SetMax(int(round(v_max * 1000.0)))

    # Time Window (VRPTW) and Vehicle Duration / Shift Constraints
    has_time_windows = any(
        s.time_window is not None or s.soft_time_window is not None for s in all_locations
    )
    has_pdp = any(s.pickup_stop_id is not None for s in all_locations)
    has_duration_limits = (
        max_route_duration_minutes is not None
        or any(
            spec.max_duration_minutes is not None
            or spec.earliest_start_min is not None
            or spec.latest_finish_min is not None
            for spec in active_specs
        )
    )
    time_dimension = None

    if has_time_windows or has_pdp or has_duration_limits:
        km_per_min = max(average_speed_kmh / 60.0, 0.1)

        def time_callback(from_index: int, to_index: int) -> int:
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            travel_km = dist_matrix_km[from_node, to_node]
            travel_min = travel_km / km_per_min
            service_min = all_locations[from_node].service_duration
            return int(round((travel_min + service_min) * 10.0))  # scaled by 10 (deciminutes)

        time_callback_index = routing.RegisterTransitCallback(time_callback)
        MAX_HORIZON = 144000  # 10 days
        routing.AddDimension(
            time_callback_index,
            MAX_HORIZON,
            MAX_HORIZON,
            False,
            "Time",
        )
        time_dimension = routing.GetDimensionOrDie("Time")

        # Apply Hard and Soft Time Windows
        for node_idx, loc in enumerate(all_locations):
            index = manager.NodeToIndex(node_idx)
            if loc.time_window is not None:
                start_dm = int(round(loc.time_window[0] * 10.0))
                end_dm = int(round(loc.time_window[1] * 10.0))
                time_dimension.CumulVar(index).SetRange(start_dm, end_dm)

            if loc.soft_time_window is not None:
                soft_start_dm = int(round(loc.soft_time_window[0] * 10.0))
                soft_end_dm = int(round(loc.soft_time_window[1] * 10.0))
                early_cost = int(round(loc.early_penalty_cost * 10.0)) if loc.early_penalty_cost else 10
                late_cost = int(round(loc.late_penalty_cost * 10.0)) if loc.late_penalty_cost else 10
                time_dimension.SetCumulVarSoftLowerBound(index, soft_start_dm, early_cost)
                time_dimension.SetCumulVarSoftUpperBound(index, soft_end_dm, late_cost)

        # Apply Vehicle Shift Availability and Max Duration / Working Time Limits
        for v_idx, spec in enumerate(active_specs):
            start_idx = routing.Start(v_idx)
            end_idx = routing.End(v_idx)

            if spec.earliest_start_min is not None:
                time_dimension.CumulVar(start_idx).SetMin(int(round(spec.earliest_start_min * 10.0)))
            if spec.latest_finish_min is not None:
                time_dimension.CumulVar(end_idx).SetMax(int(round(spec.latest_finish_min * 10.0)))

            v_max_dur = spec.max_duration_minutes or max_route_duration_minutes
            if v_max_dur is not None:
                routing.solver().Add(
                    time_dimension.CumulVar(end_idx) - time_dimension.CumulVar(start_idx)
                    <= int(round(v_max_dur * 10.0))
                )

    # Pickup & Delivery (PDP) Constraints
    if has_pdp:
        for delivery_node, loc in enumerate(all_locations):
            if loc.pickup_stop_id and loc.pickup_stop_id in stop_id_to_node:
                pickup_node = stop_id_to_node[loc.pickup_stop_id]
                pickup_idx = manager.NodeToIndex(pickup_node)
                delivery_idx = manager.NodeToIndex(delivery_node)

                routing.AddPickupAndDelivery(pickup_idx, delivery_idx)
                routing.solver().Add(
                    routing.VehicleVar(pickup_idx) == routing.VehicleVar(delivery_idx)
                )
                if time_dimension is not None:
                    routing.solver().Add(
                        time_dimension.CumulVar(pickup_idx) <= time_dimension.CumulVar(delivery_idx)
                    )

    # Configure Fixed Vehicle Dispatch Costs if specified
    for v_idx, spec in enumerate(active_specs):
        cost_units = int(round(spec.fixed_cost * 100))
        routing.SetFixedCostOfVehicle(cost_units, v_idx)

    # Configure Search Parameters
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.seconds = time_limit_seconds

    # Solve
    solution = routing.SolveWithParameters(search_parameters)

    if not solution:
        raise ValueError("OR-Tools failed to find a feasible routing solution under constraints")

    # Extract routes from solution
    routes: list[Route] = []
    km_per_min = max(average_speed_kmh / 60.0, 0.1)

    for vehicle_id in range(num_vehicles):
        spec = active_specs[vehicle_id]
        index = routing.Start(vehicle_id)
        route_nodes: list[int] = []

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            route_nodes.append(node)
            index = solution.Value(routing.NextVar(index))

        end_node = manager.IndexToNode(index)
        route_nodes.append(end_node)

        route_stops = [all_locations[i] for i in route_nodes]

        if len(route_stops) >= 2:
            route_dist_matrix = provider.get_distance_matrix(route_stops)
            dist_km = _route_length(list(range(len(route_stops))), route_dist_matrix)
        else:
            dist_km = 0.0

        if time_dimension is not None:
            start_cumul = solution.Min(time_dimension.CumulVar(routing.Start(vehicle_id)))
            end_cumul = solution.Min(time_dimension.CumulVar(routing.End(vehicle_id)))
            duration_min = max(0.0, (end_cumul - start_cumul) / 10.0)
        else:
            duration_min = round(dist_km / km_per_min, 2)

        non_depot_stops = [s for s in route_stops if s.id not in depot_ids]
        if non_depot_stops:
            routes.append(
                Route(
                    zone_id=vehicle_id,
                    stops=route_stops,
                    total_distance_km=float(round(dist_km, 3)),
                    total_duration_minutes=float(round(duration_min, 2)),
                    vehicle_id=spec.id,
                    vehicle_name=spec.name,
                )
            )

    return routes
