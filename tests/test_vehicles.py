"""
Test suite for Vehicle Fleet management model and multi-tenant RLS isolation.
"""

import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from fastapi.testclient import TestClient
from main import app
from routeopt.db.models import Company, Vehicle
from routeopt.db.session import admin_session, scoped_session_for_company


class TestVehicleFleet(unittest.TestCase):
    def setUp(self):
        app.state.limiter.enabled = False
        self.client = TestClient(app)

    def test_vehicle_creation_and_listing(self):
        slug = f"fleet-{uuid.uuid4().hex[:6]}"
        self.client.post(
            "/register",
            json={
                "company_slug": slug,
                "company_name": "Fleet Corp",
                "password": "password123",
            },
        )
        login_res = self.client.post(
            "/token",
            data={"username": slug, "password": "password123"},
        )
        token = login_res.json()["access_token"]

        # Create a new vehicle
        v_res = self.client.post(
            "/vehicles",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Delivery Van 101",
                "vehicle_type": "van",
                "capacity": 25.0,
                "cost_per_km": 0.85,
                "fixed_cost": 45.0,
            },
        )
        self.assertEqual(v_res.status_code, 201)
        v_data = v_res.json()
        self.assertIn("vehicle_id", v_data)
        self.assertEqual(v_data["name"], "Delivery Van 101")
        self.assertEqual(v_data["capacity"], 25.0)

        # List registered vehicles
        list_res = self.client.get(
            "/vehicles",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(list_res.status_code, 200)
        vehicles_data = list_res.json()["vehicles"]
        self.assertEqual(len(vehicles_data), 1)
        self.assertEqual(vehicles_data[0]["name"], "Delivery Van 101")

    def test_vehicle_tenant_isolation_rls(self):
        """Verify that Tenant A's registered vehicles are strictly hidden from Tenant B via RLS."""
        slug_a = f"v-tenant-a-{uuid.uuid4().hex[:6]}"
        slug_b = f"v-tenant-b-{uuid.uuid4().hex[:6]}"

        # Register & Login Tenant A
        self.client.post("/register", json={"company_slug": slug_a, "company_name": "Company A", "password": "password123"})
        token_a = self.client.post("/token", data={"username": slug_a, "password": "password123"}).json()["access_token"]

        # Register & Login Tenant B
        self.client.post("/register", json={"company_slug": slug_b, "company_name": "Company B", "password": "password123"})
        token_b = self.client.post("/token", data={"username": slug_b, "password": "password123"}).json()["access_token"]

        # Create Vehicle for Tenant A
        self.client.post(
            "/vehicles",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"name": "Tenant A Van", "capacity": 30.0},
        )

        # Tenant B requests GET /vehicles
        res_b = self.client.get("/vehicles", headers={"Authorization": f"Bearer {token_b}"})
        self.assertEqual(res_b.status_code, 200)
        # Must return 0 vehicles for Tenant B
        self.assertEqual(len(res_b.json()["vehicles"]), 0)


if __name__ == "__main__":
    unittest.main()
