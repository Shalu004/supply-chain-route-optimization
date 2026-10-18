"""
Test suite for Feature D: Route Duration and Vehicle Operating Constraints.
Covers:
1. Maximum route duration / working time limits per vehicle
2. Vehicle availability / shift start and end windows
3. Distinct start and end depot locations per vehicle
4. Clear error handling on infeasible duration requests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routeopt.clustering import Stop, VehicleSpec
from routeopt.ortools_routing import solve_ortools_vrp
from routeopt.pipeline import run_optimization


class TestFeatureDOperatingConstraints(unittest.TestCase):
    def test_max_route_duration_enforced(self):
        """
        Vehicle with a tight max_duration_minutes cannot complete all stops,
        forcing the solver to use multiple vehicles or respect the time bound.
        """
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        # Stops spaced such that travel + service takes ~30-40 minutes
        stops = [
            Stop(id="s1", lat=28.62, lon=77.22, demand=1.0, service_duration=10.0),
            Stop(id="s2", lat=28.68, lon=77.28, demand=1.0, service_duration=10.0),
        ]

        # Vehicle with ample time (120 min) can serve both
        v_ample = [VehicleSpec(id="v1", capacity=10.0, max_duration_minutes=120.0)]
        routes_ample = solve_ortools_vrp(
            stops=stops,
            n_vehicles=1,
            vehicle_capacity=10.0,
            depot=depot,
            vehicle_specs=v_ample,
            average_speed_kmh=30.0,
        )
        self.assertEqual(len(routes_ample), 1)
        self.assertTrue(routes_ample[0].total_duration_minutes <= 120.0)

        # Two vehicles with 25 min max duration can split the stops
        v_split = [
            VehicleSpec(id="v1", capacity=10.0, max_duration_minutes=65.0),
            VehicleSpec(id="v2", capacity=10.0, max_duration_minutes=65.0),
        ]
        routes_split = solve_ortools_vrp(
            stops=stops,
            n_vehicles=2,
            vehicle_capacity=10.0,
            depot=depot,
            vehicle_specs=v_split,
            average_speed_kmh=30.0,
        )
        self.assertEqual(len(routes_split), 2)
        for r in routes_split:
            self.assertTrue(r.total_duration_minutes <= 65.0)

    def test_vehicle_shift_availability(self):
        """
        Vehicle with shift [0, 60] serves earlier stop,
        vehicle with shift [60, 180] serves later stop.
        """
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        stops = [
            Stop(id="s_early", lat=28.61, lon=77.21, demand=1.0, time_window=(10.0, 45.0)),
            Stop(id="s_late", lat=28.62, lon=77.22, demand=1.0, time_window=(70.0, 120.0)),
        ]

        specs = [
            VehicleSpec(id="v_shift1", capacity=10.0, earliest_start_min=0.0, latest_finish_min=60.0),
            VehicleSpec(id="v_shift2", capacity=10.0, earliest_start_min=60.0, latest_finish_min=180.0),
        ]

        routes = solve_ortools_vrp(
            stops=stops,
            n_vehicles=2,
            vehicle_capacity=10.0,
            depot=depot,
            vehicle_specs=specs,
            average_speed_kmh=30.0,
        )

        self.assertEqual(len(routes), 2)
        route_map = {r.vehicle_id: [s.id for s in r.stops if s.id != "depot"] for r in routes}
        self.assertIn("s_early", route_map["v_shift1"])
        self.assertIn("s_late", route_map["v_shift2"])

    def test_heterogeneous_start_and_end_depots(self):
        """
        Vehicles start from distinct depot locations and return to specific end depots.
        """
        depot_north = Stop(id="depot_north", lat=28.70, lon=77.20)
        depot_south = Stop(id="depot_south", lat=28.50, lon=77.20)
        depot_east = Stop(id="depot_east", lat=28.60, lon=77.30)

        stops = [
            Stop(id="s_n", lat=28.69, lon=77.21, demand=1.0),
            Stop(id="s_s", lat=28.51, lon=77.21, demand=1.0),
        ]

        specs = [
            VehicleSpec(id="v_north", capacity=10.0, start_depot=depot_north, end_depot=depot_north),
            VehicleSpec(id="v_south", capacity=10.0, start_depot=depot_south, end_depot=depot_east),
        ]

        routes = solve_ortools_vrp(
            stops=stops,
            n_vehicles=2,
            vehicle_capacity=10.0,
            vehicle_specs=specs,
            average_speed_kmh=30.0,
        )

        self.assertEqual(len(routes), 2)
        v_north_route = next(r for r in routes if r.vehicle_id == "v_north")
        v_south_route = next(r for r in routes if r.vehicle_id == "v_south")

        # v_north starts and ends at depot_north
        self.assertEqual(v_north_route.stops[0].id, "depot_north")
        self.assertEqual(v_north_route.stops[-1].id, "depot_north")

        # v_south starts at depot_south and ends at depot_east
        self.assertEqual(v_south_route.stops[0].id, "depot_south")
        self.assertEqual(v_south_route.stops[-1].id, "depot_east")

    def test_infeasible_duration_raises_clear_error(self):
        """
        Impossibly short max duration constraint raises a descriptive ValueError.
        """
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        stops = [
            Stop(id="far1", lat=29.00, lon=77.50, demand=1.0, service_duration=60.0),
        ]

        # Max duration 5 min when service alone is 60 min
        specs = [VehicleSpec(id="v1", capacity=10.0, max_duration_minutes=5.0)]

        with self.assertRaises(ValueError) as ctx:
            solve_ortools_vrp(
                stops=stops,
                n_vehicles=1,
                vehicle_capacity=10.0,
                depot=depot,
                vehicle_specs=specs,
            )
        self.assertIn("OR-Tools failed to find a feasible routing solution", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
