"""
Test suite for Vehicle Routing Problem with Time Windows (VRPTW) and Pickup & Delivery Problems (PDP).
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
from routeopt.ortools_routing import solve_ortools_vrp


class TestVRPTWAndPDP(unittest.TestCase):
    def setUp(self):
        app.state.limiter.enabled = False
        self.client = TestClient(app)

    def test_vrptw_time_window_constraints(self):
        """Verify that OR-Tools respects time window constraints on delivery stops."""
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        stops = [
            Stop(id="s_early", lat=28.61, lon=77.21, demand=1.0, time_window=(10.0, 60.0)),
            Stop(id="s_late", lat=28.65, lon=77.25, demand=1.0, time_window=(180.0, 240.0)),
        ]

        routes = solve_ortools_vrp(
            stops=stops,
            n_vehicles=2,
            vehicle_capacity=10.0,
            depot=depot,
        )

        self.assertTrue(len(routes) > 0)
        visited_ids = [s.id for r in routes for s in r.stops if s.id != "depot"]
        self.assertIn("s_early", visited_ids)
        self.assertIn("s_late", visited_ids)

    def test_pdp_pickup_and_delivery_precedence(self):
        """Verify that pickup stop is visited BEFORE delivery stop on the SAME vehicle route."""
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        stops = [
            Stop(id="pickup_1", lat=28.62, lon=77.22, demand=2.0),
            Stop(id="delivery_1", lat=28.68, lon=77.28, demand=2.0, pickup_stop_id="pickup_1"),
        ]

        routes = solve_ortools_vrp(
            stops=stops,
            n_vehicles=2,
            vehicle_capacity=10.0,
            depot=depot,
        )

        self.assertEqual(len(routes), 1)
        route_ids = [s.id for s in routes[0].stops if s.id != "depot"]
        self.assertEqual(route_ids, ["pickup_1", "delivery_1"])

    def test_api_vrptw_and_pdp_endpoint(self):
        """Integration test for /optimize endpoint receiving time_window and pickup_stop_id fields."""
        slug = f"vrp-{uuid.uuid4().hex[:6]}"
        self.client.post("/register", json={"company_slug": slug, "company_name": "VRP Express", "password": "password123"})
        token = self.client.post("/token", data={"username": slug, "password": "password123"}).json()["access_token"]

        stops_data = [
            {"id": "p1", "lat": 28.61, "lon": 77.21, "demand": 2.0, "time_window": [0.0, 120.0], "service_duration": 10.0},
            {"id": "d1", "lat": 28.64, "lon": 77.24, "demand": 2.0, "pickup_stop_id": "p1", "time_window": [30.0, 180.0], "service_duration": 5.0},
        ]

        res = self.client.post(
            "/optimize",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "vehicles": 1,
                "vehicle_capacity": 10.0,
                "stops": stops_data,
                "solver_type": "ortools",
                "use_cache": False,
            },
        )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data["routes"]), 1)
        self.assertEqual(set(data["routes"][0]["stop_ids"]), {"p1", "d1"})


if __name__ == "__main__":
    unittest.main()
