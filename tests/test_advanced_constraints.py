"""
Test suite for Advanced Logistics Constraints (Heterogeneous capacities & max route distance limits).
"""

import unittest
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from fastapi.testclient import TestClient
from main import app
from routeopt.clustering import Stop, VehicleSpec
from routeopt.pipeline import run_optimization
from routeopt.ortools_routing import solve_ortools_vrp


def make_stops(n: int = 6) -> list[Stop]:
    return [
        Stop(id=f"stop_{i}", lat=28.60 + i * 0.01, lon=77.20 + i * 0.01, demand=4.0)
        for i in range(n)
    ]


class TestAdvancedConstraints(unittest.TestCase):
    def setUp(self):
        app.state.limiter.enabled = False
        self.client = TestClient(app)

    def test_heterogeneous_vehicle_capacities(self):
        """Test OR-Tools with a heterogeneous fleet (Small Van capacity 5, Large Truck capacity 20)."""
        stops = make_stops(5)  # 5 stops * 4.0 demand = 20.0 total demand
        depot = Stop(id="depot", lat=28.60, lon=77.20)

        vehicle_specs = [
            VehicleSpec(id="v_small", name="Small Van", capacity=5.0, fixed_cost=30.0),
            VehicleSpec(id="v_large", name="Heavy Truck", capacity=20.0, fixed_cost=80.0),
        ]

        routes = solve_ortools_vrp(
            stops=stops,
            n_vehicles=2,
            vehicle_capacity=20.0,
            depot=depot,
            vehicle_specs=vehicle_specs,
        )

        self.assertTrue(len(routes) > 0)
        # Verify no vehicle route exceeds its designated spec capacity
        for r in routes:
            v_spec = vehicle_specs[r.zone_id] if r.zone_id < len(vehicle_specs) else vehicle_specs[0]
            route_demand = sum(s.demand for s in r.stops if s.id != "depot")
            self.assertLessEqual(route_demand, v_spec.capacity)

    def test_max_route_distance_constraint(self):
        """Test max route distance constraint enforcement."""
        stops = make_stops(4)
        depot = Stop(id="depot", lat=28.60, lon=77.20)

        res = run_optimization(
            stops=stops,
            n_vehicles=2,
            vehicle_capacity=20.0,
            depot=depot,
            max_route_distance_km=15.0,
        )

        for route in res.routes:
            self.assertLessEqual(route.total_distance_km, 15.0)

    def test_api_optimize_with_advanced_constraints(self):
        slug = f"adv-{uuid.uuid4().hex[:6]}"
        self.client.post("/register", json={"company_slug": slug, "company_name": "Adv Logistics", "password": "password123"})
        token = self.client.post("/token", data={"username": slug, "password": "password123"}).json()["access_token"]

        stops = [
            {"id": f"s_{i}", "lat": 28.60 + i * 0.01, "lon": 77.20 + i * 0.01, "demand": 3.0}
            for i in range(4)
        ]

        opt_res = self.client.post(
            "/optimize",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "vehicles": 2,
                "vehicle_capacity": 15.0,
                "stops": stops,
                "vehicle_specs": [
                    {"id": "v1", "name": "Van A", "capacity": 10.0, "cost_per_km": 0.8, "fixed_cost": 40.0},
                    {"id": "v2", "name": "Van B", "capacity": 15.0, "cost_per_km": 0.9, "fixed_cost": 50.0},
                ],
                "max_route_distance_km": 20.0,
            },
        )
        self.assertEqual(opt_res.status_code, 200)
        data = opt_res.json()
        self.assertIn("routes", data)
        self.assertEqual(data["summary"]["solver_used"], "ortools")


if __name__ == "__main__":
    unittest.main()
