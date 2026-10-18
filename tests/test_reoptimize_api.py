"""
Test suite for Dynamic Reoptimization and Simulation FastAPI endpoints.
"""

import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from fastapi.testclient import TestClient
from main import app


class TestReoptimizationAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.state.limiter.enabled = False
        cls.client = TestClient(app)
        cls.slug = f"dyn-{uuid.uuid4().hex[:6]}"
        reg = cls.client.post(
            "/api/v1/auth/register",
            json={"name": "Dynamic Logistics", "slug": cls.slug, "password": "password123"},
        )
        cls.token = reg.json()["token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    def test_api_insert_order(self):
        """Test POST /api/v1/reoptimize/insert-order."""
        payload = {
            "new_stop": {"id": "s_new", "lat": 28.63, "lon": 77.23, "demand": 1.0},
            "active_routes": [
                {
                    "zone_id": 0,
                    "vehicle_id": "v1",
                    "stop_ids": ["depot", "s1", "depot"],
                    "stops": [
                        {"id": "depot", "lat": 28.60, "lon": 77.20, "demand": 0.0},
                        {"id": "s1", "lat": 28.61, "lon": 77.21, "demand": 2.0},
                        {"id": "depot", "lat": 28.60, "lon": 77.20, "demand": 0.0},
                    ],
                    "total_distance_km": 10.0,
                    "total_duration_minutes": 25.0,
                }
            ],
            "vehicle_specs": [{"id": "v1", "capacity": 10.0}],
            "depot": {"lat": 28.60, "lon": 77.20},
        }

        res = self.client.post("/api/v1/reoptimize/insert-order", headers=self.headers, json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["event_type"], "INSERT_ORDER")
        self.assertIn("v1", data["affected_vehicle_ids"])

    def test_api_cancel_order(self):
        """Test POST /api/v1/reoptimize/cancel-order."""
        payload = {
            "cancelled_stop_id": "s2",
            "active_routes": [
                {
                    "zone_id": 0,
                    "vehicle_id": "v1",
                    "stops": [
                        {"id": "depot", "lat": 28.60, "lon": 77.20, "demand": 0.0},
                        {"id": "s1", "lat": 28.61, "lon": 77.21, "demand": 1.0},
                        {"id": "s2", "lat": 28.62, "lon": 77.22, "demand": 1.0},
                        {"id": "depot", "lat": 28.60, "lon": 77.20, "demand": 0.0},
                    ],
                    "total_distance_km": 15.0,
                    "total_duration_minutes": 35.0,
                }
            ],
        }

        res = self.client.post("/api/v1/reoptimize/cancel-order", headers=self.headers, json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["event_type"], "CANCEL_ORDER")

    def test_api_disruption_simulation(self):
        """Test POST /api/v1/simulate."""
        payload = {
            "scenario_type": "dock_delay",
            "scenario_params": {"extra_dwell_minutes": 20.0, "stop_id": "s1"},
            "baseline_routes": [
                {
                    "zone_id": 0,
                    "vehicle_id": "v1",
                    "stops": [
                        {"id": "depot", "lat": 28.60, "lon": 77.20, "demand": 0.0},
                        {"id": "s1", "lat": 28.61, "lon": 77.21, "demand": 1.0},
                        {"id": "depot", "lat": 28.60, "lon": 77.20, "demand": 0.0},
                    ],
                    "total_distance_km": 10.0,
                    "total_duration_minutes": 25.0,
                }
            ],
            "depot": {"lat": 28.60, "lon": 77.20},
        }

        res = self.client.post("/api/v1/simulate", headers=self.headers, json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["scenario_type"], "dock_delay")
        self.assertIn("duration_minutes", data)
        self.assertEqual(data["duration_minutes"]["delta"], 20.0)

    def test_api_sustainability_assessment(self):
        """Test POST /api/v1/sustainability."""
        payload = {
            "fuel_type": "diesel",
            "routes": [
                {
                    "zone_id": 0,
                    "vehicle_id": "v1",
                    "stops": [
                        {"id": "depot", "lat": 28.60, "lon": 77.20, "demand": 0.0},
                        {"id": "s1", "lat": 28.61, "lon": 77.21, "demand": 1.0},
                        {"id": "depot", "lat": 28.60, "lon": 77.20, "demand": 0.0},
                    ],
                    "total_distance_km": 100.0,
                    "total_duration_minutes": 180.0,
                }
            ],
        }

        res = self.client.post("/api/v1/sustainability", headers=self.headers, json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_distance_km"], 100.0)
        self.assertAlmostEqual(data["fuel_consumption_liters"], 11.5, places=1)
        self.assertTrue(data["composite_sustainability_score"] > 0)


if __name__ == "__main__":
    unittest.main()
