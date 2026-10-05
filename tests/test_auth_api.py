"""
Test suite for FastAPI endpoints and JWT authentication.
"""

import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from fastapi.testclient import TestClient
from main import app
from routeopt.db.models import Company, OptimizationRun, RouteRecord, Stop, Vehicle
from routeopt.db.session import admin_session


class TestAuthAPI(unittest.TestCase):
    def setUp(self):
        app.state.limiter.enabled = False
        self.client = TestClient(app)

    @classmethod
    def setUpClass(cls):
        """Clean test database entries."""
        with admin_session() as session:
            session.query(RouteRecord).delete()
            session.query(OptimizationRun).delete()
            session.query(Stop).delete()
            session.query(Vehicle).delete()
            session.query(Company).delete()

    def test_register_success(self):
        slug = f"company-{uuid.uuid4().hex[:6]}"
        response = self.client.post(
            "/register",
            json={
                "company_slug": slug,
                "company_name": "Test Company",
                "password": "password123",
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("company_id", data)
        self.assertEqual(data["company_slug"], slug)

    def test_register_duplicate_slug_fails(self):
        slug = f"dup-{uuid.uuid4().hex[:6]}"
        self.client.post(
            "/register",
            json={
                "company_slug": slug,
                "company_name": "Company One",
                "password": "password123",
            },
        )
        response = self.client.post(
            "/register",
            json={
                "company_slug": slug,
                "company_name": "Company Two",
                "password": "password123",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Company slug already registered")

    def test_login_wrong_password_fails(self):
        slug = f"loginbad-{uuid.uuid4().hex[:6]}"
        self.client.post(
            "/register",
            json={
                "company_slug": slug,
                "company_name": "Login Test",
                "password": "correctpassword",
            },
        )
        response = self.client.post(
            "/token",
            data={"username": slug, "password": "wrongpassword"},
        )
        self.assertEqual(response.status_code, 401)

    def test_login_success_returns_jwt(self):
        slug = f"logingood-{uuid.uuid4().hex[:6]}"
        self.client.post(
            "/register",
            json={
                "company_slug": slug,
                "company_name": "Login Good",
                "password": "goodpassword123",
            },
        )
        response = self.client.post(
            "/token",
            data={"username": slug, "password": "goodpassword123"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["token_type"], "bearer")

    def test_optimize_without_token_fails(self):
        response = self.client.post(
            "/optimize",
            json={
                "vehicles": 2,
                "vehicle_capacity": 10.0,
                "stops": [{"id": "s1", "lat": 28.6, "lon": 77.2, "demand": 1.0}],
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_optimize_invalid_token_fails(self):
        response = self.client.post(
            "/optimize",
            headers={"Authorization": "Bearer invalid_garbage_token"},
            json={
                "vehicles": 2,
                "vehicle_capacity": 10.0,
                "stops": [{"id": "s1", "lat": 28.6, "lon": 77.2, "demand": 1.0}],
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_optimize_valid_token_succeeds(self):
        slug = f"opt-{uuid.uuid4().hex[:6]}"
        self.client.post(
            "/register",
            json={
                "company_slug": slug,
                "company_name": "Optimization Corp",
                "password": "password123",
            },
        )
        login_res = self.client.post(
            "/token",
            data={"username": slug, "password": "password123"},
        )
        token = login_res.json()["access_token"]

        stops = [
            {"id": f"stop_{i}", "lat": 28.60 + i * 0.01, "lon": 77.20 + i * 0.01, "demand": 1.0}
            for i in range(5)
        ]

        opt_res = self.client.post(
            "/optimize",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "vehicles": 2,
                "vehicle_capacity": 5.0,
                "stops": stops,
            },
        )
        self.assertEqual(opt_res.status_code, 200)
        data = opt_res.json()
        self.assertIn("request_id", data)
        self.assertEqual(data["company_id"], slug)
        self.assertEqual(len(data["routes"]), 2)

    def test_list_runs_returns_company_runs(self):
        slug = f"runs-{uuid.uuid4().hex[:6]}"
        self.client.post(
            "/register",
            json={
                "company_slug": slug,
                "company_name": "Runs Corp",
                "password": "password123",
            },
        )
        login_res = self.client.post(
            "/token",
            data={"username": slug, "password": "password123"},
        )
        token = login_res.json()["access_token"]

        stops = [
            {"id": f"stop_{i}", "lat": 28.60 + i * 0.01, "lon": 77.20 + i * 0.01, "demand": 1.0}
            for i in range(4)
        ]
        self.client.post(
            "/optimize",
            headers={"Authorization": f"Bearer {token}"},
            json={"vehicles": 2, "vehicle_capacity": 5.0, "stops": stops},
        )

        runs_res = self.client.get(
            "/runs",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(runs_res.status_code, 200)
        data = runs_res.json()
        self.assertEqual(data["company_id"], slug)
        self.assertEqual(len(data["runs"]), 1)


if __name__ == "__main__":
    unittest.main()
