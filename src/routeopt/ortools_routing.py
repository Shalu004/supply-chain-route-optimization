"""
Google OR-Tools solver integration for Vehicle Routing Problem (VRP / CVRP / VRPTW / PDP).

Provides exact / metaheuristic VRP solving with vehicle capacity constraints,
heterogeneous fleet capacities, max route distance limits, time windows (VRPTW),
pickup & delivery constraints (PDP), and native multi-vehicle routing.
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
    average_speed_kmh: float = 30.0,
) -> list[Route]:
    """
    Solve the Vehicle Routing Problem (CVRP / VRPTW / PDP) using Google OR-Tools.

    Args:
        stops: list of delivery stops to visit.
        n_vehicles: number of available vehicles.
        vehicle_capacity: default maximum demand capacity per vehicle.
        depot: optional warehouse depot location.
        time_limit_seconds: maximum execution time limit for the solver.
        distance_provider: distance matrix provider (defaults to Haversine).
        vehicle_specs: optional heterogeneous vehicle specifications list.
        max_route_distance_km: optional maximum route distance constraint per vehicle.
        average_speed_kmh: assumed average fleet speed in km/h for time window calculations.

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

    # Construct complete location list
    if depot is not None:
        all_locations = [depot] + list(stops)
        depot_index = 0
    else:
        all_locations = list(stops)
        depot_index = 0

    num_locations = len(all_locations)
    stop_id_to_node = {s.id: idx for idx, s in enumerate(all_locations)}
    
    # Determine vehicle count and per-vehicle capacity array
    if vehicle_specs:
        num_vehicles = min(len(vehicle_specs), num_locations)
        active_specs = vehicle_specs[:num_vehicles]
    else:
        num_vehicles = min(n_vehicles, num_locations)
        active_specs = [
            VehicleSpec(id=f"v_{i}", capacity=vehicle_capacity)
            for i in range(num_vehicles)
        ]

    # Calculate distance matrix (converted to integer meters for OR-Tools)
    dist_matrix_km = provider.get_distance_matrix(all_locations)
    dist_matrix_meters = (dist_matrix_km * 1000.0).astype(int)

    # Scale demands and vehicle capacity to integer units (scale factor 100)
    SCALE = 100
    demands = [int(round(s.demand * SCALE)) for s in all_locations]
    if depot is not None:
        demands[0] = 0

    vehicle_capacities = [int(round(spec.capacity * SCALE)) for spec in active_specs]

    # Initialize OR-Tools Routing Index Manager and Model
    manager = pywrapcp.RoutingIndexManager(num_locations, num_vehicles, depot_index)
    routing = pywrapcp.RoutingModel(manager)

    # Transit distance callback
    def distance_callback(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(dist_matrix_meters[from_node, to_node])

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Capacity demand callback
    def demand_callback(from_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        return demands[from_node]

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,  # null capacity slack
        vehicle_capacities,  # heterogeneous vehicle capacities
        True,  # start cumul to zero
        "Capacity",
    )

    # Maximum Route Distance Dimension Constraint
    if max_route_distance_km is not None or any(s.max_distance_km for s in active_specs):
        max_dist_meters = int(round((max_route_distance_km or 10000.0) * 1000.0))
        routing.AddDimension(
            transit_callback_index,
            0,  # no slack
            max_dist_meters,  # max distance per route
            True,  # start cumul to zero
            "Distance",
        )

    # Time Window (VRPTW) Dimension
    has_time_windows = any(s.time_window is not None for s in all_locations)
    has_pdp = any(s.pickup_stop_id is not None for s in all_locations)
    time_dimension = None

    if has_time_windows or has_pdp:
        # Convert distance (km) to travel time (minutes) at average speed
        km_per_min = max(average_speed_kmh / 60.0, 0.1)

        def time_callback(from_index: int, to_index: int) -> int:
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            travel_km = dist_matrix_km[from_node, to_node]
            travel_min = travel_km / km_per_min
            service_min = all_locations[from_node].service_duration
            return int(round((travel_min + service_min) * 10.0))  # scaled by 10 (deciminutes)

        time_callback_index = routing.RegisterTransitCallback(time_callback)
        # Max horizon 14400 deciminutes = 24 hours
        MAX_HORIZON = 144000
        routing.AddDimension(
            time_callback_index,
            MAX_HORIZON,  # allow waiting slack at stops
            MAX_HORIZON,  # max route time horizon
            False,  # don't force start to zero if vehicle leaves later
            "Time",
        )
        time_dimension = routing.GetDimensionOrDie("Time")

        # Apply Time Window ranges per node
        for node_idx, loc in enumerate(all_locations):
            index = manager.NodeToIndex(node_idx)
            if loc.time_window is not None:
                start_dm = int(round(loc.time_window[0] * 10.0))
                end_dm = int(round(loc.time_window[1] * 10.0))
                time_dimension.CumulVar(index).SetRange(start_dm, end_dm)

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
    if vehicle_specs:
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
    for vehicle_id in range(num_vehicles):
        index = routing.Start(vehicle_id)
        route_nodes: list[int] = []

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            route_nodes.append(node)
            index = solution.Value(routing.NextVar(index))

        # Append end depot node if depot provided or route non-empty
        end_node = manager.IndexToNode(index)
        route_nodes.append(end_node)

        # Convert node indices back to Stop objects
        route_stops = [all_locations[i] for i in route_nodes]

        # Calculate exact route distance in km using distance provider
        if len(route_stops) >= 2:
            route_dist_matrix = provider.get_distance_matrix(route_stops)
            dist_km = _route_length(list(range(len(route_stops))), route_dist_matrix)
        else:
            dist_km = 0.0

        # Only include vehicle routes that visit at least one non-depot stop
        non_depot_stops = [s for s in route_stops if depot is None or s != depot]
        if non_depot_stops:
            routes.append(
                Route(
                    zone_id=vehicle_id,
                    stops=route_stops,
                    total_distance_km=float(round(dist_km, 3)),
                )
            )

    return routes
