"""
Test suite for Google OR-Tools solver and solver coexistence / comparison.
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from routeopt.clustering import Stop
from routeopt.pipeline import run_optimization
from routeopt.ortools_routing import solve_ortools_vrp


def make_sample_stops(n: int = 12) -> list[Stop]:
    stops = []
    for i in range(n):
        lat = 28.60 + (i % 4) * 0.01
        lon = 77.20 + (i // 4) * 0.01
        stops.append(Stop(id=f"stop_{i}", lat=lat, lon=lon, demand=2.0))
    return stops


class TestORToolsSolver(unittest.TestCase):
    def test_ortools_vrp_solving(self):
        stops = make_sample_stops(10)
        depot = Stop(id="depot", lat=28.60, lon=77.20)
        
        routes = solve_ortools_vrp(
            stops=stops,
            n_vehicles=3,
            vehicle_capacity=10.0,
            depot=depot,
        )
        
        self.assertGreater(len(routes), 0)
        self.assertLessEqual(len(routes), 3)
        
        # Verify all stops are visited
        visited_ids = set()
        for route in routes:
            # Check vehicle capacity constraint
            total_demand = sum(s.demand for s in route.stops if s.id != "depot")
            self.assertLessEqual(total_demand, 10.0)
            for stop in route.stops:
                if stop.id != "depot":
                    visited_ids.add(stop.id)
                    
        self.assertEqual(len(visited_ids), 10)

    def test_solver_coexistence_comparison(self):
        """Compare OR-Tools solver vs Heuristic (K-Means + 2-Opt) solver on identical dataset."""
        stops = make_sample_stops(12)
        depot = Stop(id="depot", lat=28.60, lon=77.20)

        # Run with OR-Tools solver
        res_ortools = run_optimization(
            stops=stops,
            n_vehicles=3,
            vehicle_capacity=10.0,
            depot=depot,
            solver_type="ortools",
        )

        # Run with Heuristic solver
        res_heuristic = run_optimization(
            stops=stops,
            n_vehicles=3,
            vehicle_capacity=10.0,
            depot=depot,
            solver_type="heuristic",
        )

        self.assertEqual(res_ortools.solver_used, "ortools")
        self.assertEqual(res_heuristic.solver_used, "heuristic")

        # Both solvers must produce valid non-empty route lists
        self.assertTrue(len(res_ortools.routes) > 0)
        self.assertTrue(len(res_heuristic.routes) > 0)

        # Verify distance and vehicle bounds
        self.assertGreater(res_ortools.total_distance_km, 0.0)
        self.assertGreater(res_heuristic.total_distance_km, 0.0)
        self.assertLessEqual(res_ortools.vehicles_used, 3)
        self.assertLessEqual(res_heuristic.vehicles_used, 3)

    def test_pipeline_fallback_behaviour(self):
        """Test that invalid solver string defaults/falls back gracefully to heuristic solver."""
        stops = make_sample_stops(6)
        res = run_optimization(
            stops=stops,
            n_vehicles=2,
            vehicle_capacity=10.0,
            solver_type="non_existent_solver",
        )
        self.assertEqual(res.solver_used, "heuristic")
        self.assertTrue(len(res.routes) > 0)


if __name__ == "__main__":
    unittest.main()
