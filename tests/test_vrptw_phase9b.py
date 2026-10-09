"""
Test suite for Phase 9B: Soft Time Windows and Violation Penalties.
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


class TestPhase9BSoftTimeWindows(unittest.TestCase):
    def setUp(self):
        app.state.limiter.enabled = False
        self.client = TestClient(app)

    def test_soft_time_window_early_and_late_penalties(self):
        """Verify solver produces valid route when soft time windows and penalty costs are specified."""
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        stops = [
            Stop(
                id="s_soft",
                lat=28.61,
                lon=77.21,
                demand=1.0,
                soft_time_window=(15.0, 45.0),
                early_penalty_cost=2.0,
                late_penalty_cost=5.0,
            ),
        ]

        routes = solve_ortools_vrp(
            stops=stops,
            n_vehicles=1,
            vehicle_capacity=10.0,
            depot=depot,
        )

        self.assertEqual(len(routes), 1)
        visited_ids = [s.id for s in routes[0].stops if s.id != "depot"]
        self.assertEqual(visited_ids, ["s_soft"])

    def test_hard_and_soft_time_window_combination(self):
        """Hard constraint enforces feasibility range while soft window optimizes arrival time within range."""
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        stops = [
            Stop(
                id="s_combo",
                lat=28.62,
                lon=77.22,
                demand=1.0,
                time_window=(0.0, 120.0),  # Hard window 0..120 min
                soft_time_window=(20.0, 60.0),  # Preferred soft window 20..60 min
                early_penalty_cost=1.0,
                late_penalty_cost=3.0,
            ),
        ]

        res = run_optimization(
            stops=stops,
            n_vehicles=1,
            vehicle_capacity=10.0,
            depot=depot,
            solver_type="ortools",
        )

        self.assertEqual(len(res.routes), 1)
        self.assertEqual(res.solver_used, "ortools")

    def test_soft_time_window_input_validation(self):
        """API rejects invalid soft_time_window input."""
        slug = f"softval-{uuid.uuid4().hex[:6]}"
        self.client.post("/register", json={"company_slug": slug, "company_name": "Soft Val Co", "password": "password123"})
        token = self.client.post("/token", data={"username": slug, "password": "password123"}).json()["access_token"]

        # Inverted soft time window [80, 20]
        res = self.client.post(
            "/optimize",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "vehicles": 1,
                "vehicle_capacity": 10.0,
                "stops": [
                    {
                        "id": "s1",
                        "lat": 28.61,
                        "lon": 77.21,
                        "soft_time_window": [80.0, 20.0],
                        "late_penalty_cost": 5.0,
                    }
                ],
            },
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("latest time (20.0) cannot be earlier", res.text)

    def test_api_soft_time_window_endpoint(self):
        """Integration test for API /optimize endpoint receiving soft_time_window and penalty costs."""
        slug = f"softapi-{uuid.uuid4().hex[:6]}"
        self.client.post("/register", json={"company_slug": slug, "company_name": "Soft API Co", "password": "password123"})
        token = self.client.post("/token", data={"username": slug, "password": "password123"}).json()["access_token"]

        res = self.client.post(
            "/optimize",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "vehicles": 1,
                "vehicle_capacity": 10.0,
                "stops": [
                    {
                        "id": "s1",
                        "lat": 28.61,
                        "lon": 77.21,
                        "demand": 2.0,
                        "soft_time_window": [10.0, 60.0],
                        "early_penalty_cost": 1.5,
                        "late_penalty_cost": 4.0,
                    }
                ],
                "depot": {"lat": 28.60, "lon": 77.20},
                "solver_type": "ortools",
            },
        )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data["routes"]), 1)
        self.assertEqual(data["routes"][0]["stop_ids"], ["depot", "s1", "depot"])


if __name__ == "__main__":
    unittest.main()
