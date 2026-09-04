"""
Test suite for the optimization engine.

Run with: python -m pytest tests/ -v
(or `python -m unittest tests.test_engine` if pytest isn't installed)
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routeopt.clustering import Stop, balance_zones_by_capacity, cluster_stops
from routeopt.pipeline import CostModel, run_optimization
from routeopt.routing import Route, solve_route


def make_grid_stops(n: int) -> list[Stop]:
    """Deterministic synthetic stops spread over a small lat/lon grid."""
    stops = []
    for i in range(n):
        lat = 28.60 + (i % 5) * 0.01
        lon = 77.20 + (i // 5) * 0.01
        stops.append(Stop(id=f"stop_{i}", lat=lat, lon=lon, demand=1.0))
    return stops


class TestClustering(unittest.TestCase):
    def test_cluster_count_matches_n_zones(self):
        stops = make_grid_stops(20)
        zones = cluster_stops(stops, n_zones=4)
        self.assertEqual(len(zones), 4)

    def test_all_stops_assigned_exactly_once(self):
        stops = make_grid_stops(15)
        zones = cluster_stops(stops, n_zones=3)
        assigned_ids = sorted(s.id for z in zones.values() for s in z)
        expected_ids = sorted(s.id for s in stops)
        self.assertEqual(assigned_ids, expected_ids)

    def test_empty_stops_raises(self):
        with self.assertRaises(ValueError):
            cluster_stops([], n_zones=2)

    def test_more_zones_than_stops_raises(self):
        stops = make_grid_stops(3)
        with self.assertRaises(ValueError):
            cluster_stops(stops, n_zones=5)

    def test_capacity_balancing_respects_limit(self):
        stops = make_grid_stops(10)
        for s in stops:
            s.demand = 3.0
        zones = cluster_stops(stops, n_zones=2)
        balanced = balance_zones_by_capacity(zones, vehicle_capacity=15.0)
        for zid, zone_stops in balanced.items():
            total_demand = sum(s.demand for s in zone_stops)
            self.assertLessEqual(total_demand, 15.0, f"zone {zid} exceeds capacity")

    def test_no_stops_lost_during_rebalancing(self):
        stops = make_grid_stops(12)
        for s in stops:
            s.demand = 2.0
        zones = cluster_stops(stops, n_zones=3)
        balanced = balance_zones_by_capacity(zones, vehicle_capacity=10.0)
        assigned_ids = sorted(s.id for z in balanced.values() for s in z)
        expected_ids = sorted(s.id for s in stops)
        self.assertEqual(assigned_ids, expected_ids)


class TestRouting(unittest.TestCase):
    def test_single_stop_route(self):
        stop = Stop(id="a", lat=28.6, lon=77.2)
        route = solve_route(0, [stop])
        self.assertEqual(len(route.stops), 1)
        self.assertEqual(route.total_distance_km, 0.0)

    def test_empty_route(self):
        route = solve_route(0, [])
        self.assertEqual(route.stops, [])
        self.assertEqual(route.total_distance_km, 0.0)

    def test_route_visits_every_stop_exactly_once(self):
        stops = make_grid_stops(8)
        route = solve_route(0, stops)
        visited_ids = sorted(s.id for s in route.stops)
        expected_ids = sorted(s.id for s in stops)
        self.assertEqual(visited_ids, expected_ids)

    def test_optimized_route_not_longer_than_input_order(self):
        """2-opt must never produce a worse route than the naive input order."""
        stops = make_grid_stops(10)
        from routeopt.routing import _haversine_matrix, _route_length

        naive_dist = _route_length(
            list(range(len(stops))), _haversine_matrix(stops)
        )
        route = solve_route(0, stops)
        self.assertLessEqual(route.total_distance_km, naive_dist + 1e-6)

    def test_distance_is_non_negative(self):
        stops = make_grid_stops(6)
        route = solve_route(0, stops)
        self.assertGreaterEqual(route.total_distance_km, 0.0)


class TestPipeline(unittest.TestCase):
    def test_full_pipeline_runs_end_to_end(self):
        stops = make_grid_stops(30)
        result = run_optimization(stops, n_vehicles=4, vehicle_capacity=20.0)
        self.assertEqual(result.vehicles_used <= 4, True)
        self.assertGreater(result.total_distance_km, 0)
        self.assertGreater(result.total_cost, 0)

    def test_optimized_cost_not_worse_than_baseline(self):
        """
        The whole point of the product: optimized cost should be <= a naive
        single-route baseline. This is the assertion that would catch a
        regression in the clustering/routing logic before it reached prod.
        """
        stops = make_grid_stops(25)
        result = run_optimization(stops, n_vehicles=3, vehicle_capacity=15.0)
        self.assertLessEqual(result.total_cost, result.baseline_cost + 1e-6)
        self.assertGreaterEqual(result.cost_reduction_pct, 0.0)

    def test_custom_cost_model_applied(self):
        stops = make_grid_stops(10)
        cheap = CostModel(cost_per_km=0.1, cost_per_vehicle=1.0)
        expensive = CostModel(cost_per_km=5.0, cost_per_vehicle=200.0)
        cheap_result = run_optimization(stops, n_vehicles=2, vehicle_capacity=10.0, cost_model=cheap)
        expensive_result = run_optimization(stops, n_vehicles=2, vehicle_capacity=10.0, cost_model=expensive)
        self.assertLess(cheap_result.total_cost, expensive_result.total_cost)


if __name__ == "__main__":
    unittest.main()
