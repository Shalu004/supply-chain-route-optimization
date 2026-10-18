"""
Test suite for Dynamic Route Reoptimization Engine.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routeopt.clustering import Stop, VehicleSpec
from routeopt.dynamic import (
    reoptimize_cancel_order,
    reoptimize_insert_order,
    reoptimize_traffic_delay,
    reoptimize_vehicle_breakdown,
)
from routeopt.routing import Route


class TestDynamicRouteReoptimization(unittest.TestCase):
    def setUp(self):
        self.depot = Stop(id="depot", lat=28.60, lon=77.20)
        self.s1 = Stop(id="s1", lat=28.62, lon=77.22, demand=2.0, service_duration=5.0)
        self.s2 = Stop(id="s2", lat=28.64, lon=77.24, demand=3.0, service_duration=5.0)
        self.s3 = Stop(id="s3", lat=28.66, lon=77.26, demand=4.0, service_duration=5.0)
        self.s4 = Stop(id="s4", lat=28.58, lon=77.18, demand=2.0, service_duration=5.0)

        self.route_v1 = Route(
            zone_id=0,
            stops=[self.depot, self.s1, self.s2, self.depot],
            total_distance_km=15.0,
            total_duration_minutes=40.0,
            vehicle_id="v1",
            vehicle_name="Van 1",
        )
        self.route_v2 = Route(
            zone_id=1,
            stops=[self.depot, self.s3, self.s4, self.depot],
            total_distance_km=25.0,
            total_duration_minutes=60.0,
            vehicle_id="v2",
            vehicle_name="Van 2",
        )

        self.specs = [
            VehicleSpec(id="v1", capacity=10.0),
            VehicleSpec(id="v2", capacity=10.0),
        ]

    def test_reoptimize_insert_order_feasible(self):
        """New order is inserted into the optimal active vehicle route."""
        new_order = Stop(id="s_rush", lat=28.63, lon=77.23, demand=2.0)
        active_routes = [self.route_v1, self.route_v2]

        result = reoptimize_insert_order(
            active_routes=active_routes,
            new_stop=new_order,
            vehicle_specs=self.specs,
            depot=self.depot,
            completed_stop_ids={"s1"},  # s1 is already delivered
        )

        self.assertTrue(result.success)
        self.assertEqual(len(result.unassigned_stops), 0)
        self.assertEqual(result.event_type, "INSERT_ORDER")
        self.assertTrue(len(result.affected_vehicle_ids) == 1)

        # Check that s_rush is in the affected route
        affected_id = result.affected_vehicle_ids[0]
        affected_route = next(r for r in result.routes if (getattr(r, "vehicle_id", None) or f"v_{r.zone_id}") == affected_id)
        visited_ids = [s.id for s in affected_route.stops]
        self.assertIn("s_rush", visited_ids)

        # Operational Invariant: completed s1 must still precede s_rush
        idx_s1 = visited_ids.index("s1")
        idx_rush = visited_ids.index("s_rush")
        self.assertLess(idx_s1, idx_rush)

    def test_reoptimize_insert_order_capacity_infeasible(self):
        """When all vehicles are at capacity, order is marked as unassigned cleanly."""
        giant_order = Stop(id="s_huge", lat=28.63, lon=77.23, demand=20.0)  # Exceeds 10.0 capacity
        active_routes = [self.route_v1, self.route_v2]

        result = reoptimize_insert_order(
            active_routes=active_routes,
            new_stop=giant_order,
            vehicle_specs=self.specs,
            depot=self.depot,
        )

        self.assertFalse(result.success)
        self.assertEqual(len(result.unassigned_stops), 1)
        self.assertEqual(result.unassigned_stops[0].stop_id, "s_huge")

    def test_reoptimize_cancel_order(self):
        """Cancelling a pending order removes it and shortens the route."""
        active_routes = [self.route_v1, self.route_v2]
        result = reoptimize_cancel_order(
            active_routes=active_routes,
            cancelled_stop_id="s2",
            completed_stop_ids=set(),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.event_type, "CANCEL_ORDER")
        v1_updated = next(r for r in result.routes if r.vehicle_id == "v1")
        updated_stop_ids = [s.id for s in v1_updated.stops]
        self.assertNotIn("s2", updated_stop_ids)
        self.assertEqual(updated_stop_ids, ["depot", "s1", "depot"])

        # v2 should be completely untouched
        v2_updated = next(r for r in result.routes if r.vehicle_id == "v2")
        self.assertEqual(v2_updated.total_distance_km, self.route_v2.total_distance_km)

    def test_reoptimize_cancel_completed_order_fails(self):
        """Cancelling an already delivered stop raises an explicit ValueError."""
        active_routes = [self.route_v1, self.route_v2]
        with self.assertRaises(ValueError) as ctx:
            reoptimize_cancel_order(
                active_routes=active_routes,
                cancelled_stop_id="s1",
                completed_stop_ids={"s1"},
            )
        self.assertIn("already completed", str(ctx.exception))

    def test_reoptimize_vehicle_breakdown(self):
        """Breakdown of v1 reassigns its uncompleted stops to v2."""
        active_routes = [self.route_v1, self.route_v2]
        specs_ample = [VehicleSpec(id="v1", capacity=15.0), VehicleSpec(id="v2", capacity=15.0)]
        result = reoptimize_vehicle_breakdown(
            active_routes=active_routes,
            broken_vehicle_id="v1",
            vehicle_specs=specs_ample,
            depot=self.depot,
            completed_stop_ids=set(),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.event_type, "VEHICLE_BREAKDOWN")
        # v2 should have accepted the orphaned stops
        v2_route = next(r for r in result.routes if r.vehicle_id == "v2")
        v2_stops = [s.id for s in v2_route.stops]
        self.assertIn("s1", v2_stops)
        self.assertIn("s2", v2_stops)

    def test_reoptimize_traffic_delay(self):
        """Traffic delay extends vehicle duration."""
        active_routes = [self.route_v1, self.route_v2]
        result = reoptimize_traffic_delay(
            active_routes=active_routes,
            vehicle_id="v1",
            delay_minutes=25.0,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.event_type, "DELIVERY_DELAY")
        v1_updated = next(r for r in result.routes if r.vehicle_id == "v1")
        self.assertEqual(v1_updated.total_duration_minutes, 65.0)  # 40 + 25


if __name__ == "__main__":
    unittest.main()
