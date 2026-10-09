"""
Comprehensive test suite for Phase 9C: Pickup and Delivery Problem (PDP).
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


class TestPhase9CPickupAndDelivery(unittest.TestCase):
    def setUp(self):
        app.state.limiter.enabled = False
        self.client = TestClient(app)

    def test_pdp_same_vehicle_and_precedence(self):
        """Pickup stop MUST precede delivery stop on the SAME vehicle route."""
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        stops = [
            Stop(id="p1", lat=28.62, lon=77.22, demand=2.0),
            Stop(id="d1", lat=28.68, lon=77.28, demand=2.0, pickup_stop_id="p1"),
        ]

        routes = solve_ortools_vrp(
            stops=stops,
            n_vehicles=2,
            vehicle_capacity=10.0,
            depot=depot,
        )

        self.assertEqual(len(routes), 1)
        stop_ids = [s.id for s in routes[0].stops if s.id != "depot"]
        self.assertEqual(stop_ids, ["p1", "d1"])

    def test_pdp_with_time_windows(self):
        """Pickup stop and delivery stop with integrated hard time windows."""
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        stops = [
            Stop(id="p_tw", lat=28.61, lon=77.21, demand=1.0, time_window=(0.0, 30.0)),
            Stop(id="d_tw", lat=28.63, lon=77.23, demand=1.0, pickup_stop_id="p_tw", time_window=(20.0, 60.0)),
        ]

        res = run_optimization(
            stops=stops,
            n_vehicles=1,
            vehicle_capacity=10.0,
            depot=depot,
            solver_type="ortools",
        )

        self.assertEqual(len(res.routes), 1)
        stop_ids = [s.id for s in res.routes[0].stops if s.id != "depot"]
        self.assertEqual(stop_ids, ["p_tw", "d_tw"])

    def test_pdp_invalid_pickup_reference_api(self):
        """API returns 422 Unprocessable Entity when pickup_stop_id is invalid or self-referential."""
        slug = f"pdpval-{uuid.uuid4().hex[:6]}"
        self.client.post("/register", json={"company_slug": slug, "company_name": "PDP Val Co", "password": "password123"})
        token = self.client.post("/token", data={"username": slug, "password": "password123"}).json()["access_token"]

        # Case A: pickup_stop_id refers to non-existent stop
        res_a = self.client.post(
            "/optimize",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "vehicles": 1,
                "vehicle_capacity": 10.0,
                "stops": [
                    {"id": "d1", "lat": 28.61, "lon": 77.21, "pickup_stop_id": "non_existent_pickup"}
                ],
            },
        )
        self.assertEqual(res_a.status_code, 422)
        self.assertIn("referenced pickup stop ID does not exist", res_a.text)

        # Case B: pickup_stop_id refers to self
        res_b = self.client.post(
            "/optimize",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "vehicles": 1,
                "vehicle_capacity": 10.0,
                "stops": [
                    {"id": "s1", "lat": 28.61, "lon": 77.21, "pickup_stop_id": "s1"}
                ],
            },
        )
        self.assertEqual(res_b.status_code, 422)
        self.assertIn("cannot be its own pickup stop", res_b.text)

    def test_pdp_infeasible_request_handling(self):
        """API returns HTTP 422 when PDP constraints cannot be satisfied."""
        slug = f"pdpinf-{uuid.uuid4().hex[:6]}"
        self.client.post("/register", json={"company_slug": slug, "company_name": "PDP Inf Co", "password": "password123"})
        token = self.client.post("/token", data={"username": slug, "password": "password123"}).json()["access_token"]

        # Pickup time window [100, 120] is AFTER delivery time window [0, 20] -> IMPOSSIBLE
        res = self.client.post(
            "/optimize",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "vehicles": 1,
                "vehicle_capacity": 10.0,
                "stops": [
                    {"id": "p_late", "lat": 28.61, "lon": 77.21, "demand": 1.0, "time_window": [100.0, 120.0]},
                    {"id": "d_early", "lat": 28.63, "lon": 77.23, "demand": 1.0, "pickup_stop_id": "p_late", "time_window": [0.0, 20.0]},
                ],
                "depot": {"lat": 28.60, "lon": 77.20},
                "solver_type": "ortools",
            },
        )
        self.assertEqual(res.status_code, 422)
        data = res.json()
        self.assertIn("Infeasible routing request", data["detail"])


if __name__ == "__main__":
    unittest.main()
