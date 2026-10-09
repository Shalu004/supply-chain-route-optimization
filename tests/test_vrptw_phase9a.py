"""
Comprehensive test suite for Phase 9A: VRPTW Hard Time Windows and Service Durations.
"""

import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from fastapi.testclient import TestClient
from main import app
from routeopt.clustering import Stop
from routeopt.pipeline import run_optimization
from routeopt.ortools_routing import solve_ortools_vrp


class TestPhase9AHardTimeWindows(unittest.TestCase):
    def setUp(self):
        app.state.limiter.enabled = False
        self.client = TestClient(app)

    def test_feasible_route_with_hard_time_window(self):
        """1. A feasible route with a hard time window constraint."""
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        stops = [
            Stop(id="s1", lat=28.61, lon=77.21, demand=1.0, time_window=(10.0, 60.0)),
            Stop(id="s2", lat=28.62, lon=77.22, demand=1.0, time_window=(30.0, 120.0)),
        ]

        routes = solve_ortools_vrp(
            stops=stops,
            n_vehicles=2,
            vehicle_capacity=10.0,
            depot=depot,
            average_speed_kmh=30.0,
        )

        self.assertTrue(len(routes) > 0)
        visited_ids = [s.id for r in routes for s in r.stops if s.id != "depot"]
        self.assertIn("s1", visited_ids)
        self.assertIn("s2", visited_ids)

    def test_stop_with_service_duration(self):
        """2. A stop with a service duration requirement."""
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        stops = [
            Stop(id="s1", lat=28.61, lon=77.21, demand=1.0, time_window=(0.0, 120.0), service_duration=15.0),
            Stop(id="s2", lat=28.62, lon=77.22, demand=1.0, time_window=(0.0, 120.0), service_duration=20.0),
        ]

        routes = solve_ortools_vrp(
            stops=stops,
            n_vehicles=1,
            vehicle_capacity=10.0,
            depot=depot,
        )

        self.assertEqual(len(routes), 1)
        visited_ids = [s.id for s in routes[0].stops if s.id != "depot"]
        self.assertEqual(set(visited_ids), {"s1", "s2"})

    def test_infeasible_route_hard_time_window(self):
        """3. A route that becomes infeasible because of an impossible hard time window."""
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        # s_impossible is 50km away from depot. At 30km/h speed, travel time is 100 minutes.
        # But time window closes at minute 10!
        stops = [
            Stop(id="s_impossible", lat=29.05, lon=77.65, demand=1.0, time_window=(0.0, 10.0)),
        ]

        with self.assertRaises(ValueError) as ctx:
            run_optimization(
                stops=stops,
                n_vehicles=1,
                vehicle_capacity=10.0,
                depot=depot,
                solver_type="ortools",
                average_speed_kmh=30.0,
            )

        self.assertIn("Infeasible routing request", str(ctx.exception))

    def test_multiple_stops_overlapping_conflicting_windows(self):
        """4. Multiple stops with tight / conflicting time windows."""
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        # north and south are 2.2km away from depot (~4.4 min travel time).
        # Time window is (3.0, 5.0) min for both.
        stops = [
            Stop(id="north", lat=28.62, lon=77.20, demand=1.0, time_window=(3.0, 5.0)),
            Stop(id="south", lat=28.58, lon=77.20, demand=1.0, time_window=(3.0, 5.0)),
        ]

        # With 1 vehicle, visiting both within [3, 5] min window is impossible -> raises ValueError
        with self.assertRaises(ValueError):
            run_optimization(
                stops=stops,
                n_vehicles=1,
                vehicle_capacity=10.0,
                depot=depot,
                solver_type="ortools",
                average_speed_kmh=30.0,
            )

        # With 2 vehicles, each vehicle takes one stop -> feasible!
        res = run_optimization(
            stops=stops,
            n_vehicles=2,
            vehicle_capacity=10.0,
            depot=depot,
            solver_type="ortools",
            average_speed_kmh=30.0,
        )
        self.assertEqual(len(res.routes), 2)

    def test_preservation_vehicle_capacity(self):
        """5. Preservation of vehicle-capacity constraints alongside time windows."""
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        stops = [
            Stop(id="heavy1", lat=28.61, lon=77.21, demand=6.0, time_window=(0.0, 120.0)),
            Stop(id="heavy2", lat=28.62, lon=77.22, demand=6.0, time_window=(0.0, 120.0)),
        ]

        # Vehicle capacity is 10. Total demand is 12. Must split across 2 vehicles.
        routes = solve_ortools_vrp(
            stops=stops,
            n_vehicles=2,
            vehicle_capacity=10.0,
            depot=depot,
        )

        self.assertEqual(len(routes), 2)
        for r in routes:
            demand = sum(s.demand for s in r.stops if s.id != "depot")
            self.assertLessEqual(demand, 10.0)

    def test_omitted_time_windows(self):
        """6. Preservation of existing optimization behavior when time windows are omitted."""
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        stops = [
            Stop(id="s1", lat=28.61, lon=77.21, demand=2.0),
            Stop(id="s2", lat=28.62, lon=77.22, demand=2.0),
        ]

        res = run_optimization(
            stops=stops,
            n_vehicles=1,
            vehicle_capacity=10.0,
            depot=depot,
            solver_type="ortools",
        )

        self.assertEqual(res.solver_used, "ortools")
        self.assertEqual(len(res.routes), 1)

    def test_invalid_time_window_input(self):
        """7. Validation errors on invalid time-window input."""
        slug = f"twval-{uuid.uuid4().hex[:6]}"
        self.client.post("/register", json={"company_slug": slug, "company_name": "TW Val Co", "password": "password123"})
        token = self.client.post("/token", data={"username": slug, "password": "password123"}).json()["access_token"]

        # Case A: latest time < earliest time
        res_a = self.client.post(
            "/optimize",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "vehicles": 1,
                "vehicle_capacity": 10.0,
                "stops": [{"id": "s1", "lat": 28.61, "lon": 77.21, "time_window": [100.0, 50.0]}],
            },
        )
        self.assertEqual(res_a.status_code, 422)
        self.assertIn("latest time (50.0) cannot be earlier", res_a.text)

        # Case B: negative time window
        res_b = self.client.post(
            "/optimize",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "vehicles": 1,
                "vehicle_capacity": 10.0,
                "stops": [{"id": "s1", "lat": 28.61, "lon": 77.21, "time_window": [-10.0, 50.0]}],
            },
        )
        self.assertEqual(res_b.status_code, 422)
        self.assertIn("cannot be negative", res_b.text)

        # Case C: invalid list length (3 elements)
        res_c = self.client.post(
            "/optimize",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "vehicles": 1,
                "vehicle_capacity": 10.0,
                "stops": [{"id": "s1", "lat": 28.61, "lon": 77.21, "time_window": [0.0, 50.0, 100.0]}],
            },
        )
        self.assertEqual(res_c.status_code, 422)
        self.assertIn("must be a list of exactly 2 numbers", res_c.text)

    def test_api_infeasible_request_handling(self):
        """8. API response behavior for infeasible requests (HTTP 422)."""
        slug = f"twinf-{uuid.uuid4().hex[:6]}"
        self.client.post("/register", json={"company_slug": slug, "company_name": "TW Inf Co", "password": "password123"})
        token = self.client.post("/token", data={"username": slug, "password": "password123"}).json()["access_token"]

        # 50km distant stop with impossible time window closing at min 5
        res = self.client.post(
            "/optimize",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "vehicles": 1,
                "vehicle_capacity": 10.0,
                "stops": [{"id": "s_far", "lat": 29.05, "lon": 77.65, "demand": 1.0, "time_window": [0.0, 5.0]}],
                "depot": {"lat": 28.60, "lon": 77.20},
                "solver_type": "ortools",
            },
        )
        self.assertEqual(res.status_code, 422)
        data = res.json()
        self.assertIn("Infeasible routing request", data["detail"])

    def test_configurable_travel_speed(self):
        """9. Configurable average fleet speed parameter affects travel time computation."""
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        # s_mid is ~30km away. At 60 km/h, travel time = 30 minutes. Time window [0, 40] is FEASIBLE.
        # At 15 km/h, travel time = 120 minutes. Time window [0, 40] is INFEASIBLE.
        stops = [Stop(id="s_mid", lat=28.87, lon=77.20, time_window=(0.0, 40.0))]

        # High speed (60 km/h) -> Feasible
        res_fast = run_optimization(
            stops=stops,
            n_vehicles=1,
            vehicle_capacity=10.0,
            depot=depot,
            solver_type="ortools",
            average_speed_kmh=60.0,
        )
        self.assertEqual(len(res_fast.routes), 1)

        # Slow speed (15 km/h) -> Infeasible
        with self.assertRaises(ValueError):
            run_optimization(
                stops=stops,
                n_vehicles=1,
                vehicle_capacity=10.0,
                depot=depot,
                solver_type="ortools",
                average_speed_kmh=15.0,
            )


if __name__ == "__main__":
    unittest.main()
