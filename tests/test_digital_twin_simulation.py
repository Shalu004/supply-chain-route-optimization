"""
Test suite for RouteOpt Digital Twin & Disruption Simulation.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routeopt.clustering import Stop, VehicleSpec
from routeopt.routing import Route
from routeopt.simulation import run_disruption_simulation


class TestDigitalTwinSimulation(unittest.TestCase):
    def setUp(self):
        self.depot = Stop(id="depot", lat=28.60, lon=77.20)
        self.s1 = Stop(id="s1", lat=28.62, lon=77.22, demand=2.0, service_duration=5.0, time_window=(10.0, 60.0))
        self.s2 = Stop(id="s2", lat=28.64, lon=77.24, demand=3.0, service_duration=5.0, time_window=(20.0, 90.0))
        self.s3 = Stop(id="s3", lat=28.66, lon=77.26, demand=2.0, service_duration=5.0, time_window=(30.0, 120.0))

        from routeopt.distance import HaversineDistanceProvider
        from routeopt.routing import _route_length
        provider = HaversineDistanceProvider()
        r1_stops = [self.depot, self.s1, self.s2, self.depot]
        r2_stops = [self.depot, self.s3, self.depot]
        d1 = float(round(_route_length(list(range(len(r1_stops))), provider.get_distance_matrix(r1_stops)), 3))
        d2 = float(round(_route_length(list(range(len(r2_stops))), provider.get_distance_matrix(r2_stops)), 3))

        self.route_1 = Route(
            zone_id=0,
            stops=r1_stops,
            total_distance_km=d1,
            total_duration_minutes=45.0,
            vehicle_id="v1",
            vehicle_name="Fleet Van 1",
        )
        self.route_2 = Route(
            zone_id=1,
            stops=r2_stops,
            total_distance_km=d2,
            total_duration_minutes=35.0,
            vehicle_id="v2",
            vehicle_name="Fleet Van 2",
        )

        self.specs = [
            VehicleSpec(id="v1", capacity=10.0),
            VehicleSpec(id="v2", capacity=10.0),
        ]

    def test_simulation_vehicle_breakdown(self):
        """Simulation evaluates vehicle breakdown impact without mutating production state."""
        report = run_disruption_simulation(
            baseline_routes=[self.route_1, self.route_2],
            scenario_type="vehicle_breakdown",
            params={"vehicle_id": "v1"},
            vehicle_specs=self.specs,
            depot=self.depot,
        )

        self.assertEqual(report.scenario_type, "vehicle_breakdown")
        self.assertIn("v1", report.description)
        self.assertTrue(report.execution_time_seconds >= 0)
        self.assertIsNotNone(report.distance_km)
        self.assertIsNotNone(report.operating_cost_usd)
        self.assertIsNotNone(report.co2_emissions_kg)

        # Baseline routes in report match original input
        self.assertEqual(len(report.baseline_routes), 2)

    def test_simulation_emergency_order(self):
        """Simulation introduces on-demand order and computes metrics delta."""
        report = run_disruption_simulation(
            baseline_routes=[self.route_1, self.route_2],
            scenario_type="emergency_order",
            params={"id": "rush-99", "lat": 28.63, "lon": 77.23, "demand": 1.5, "service_duration": 10.0},
            vehicle_specs=self.specs,
            depot=self.depot,
        )

        self.assertEqual(report.scenario_type, "emergency_order")
        self.assertGreaterEqual(report.distance_km.simulated_value, report.distance_km.baseline_value)
        self.assertTrue(any("rush-99" in r["stop_ids"] for r in report.simulated_routes))

    def test_simulation_traffic_surge(self):
        """Simulation computes delay impact and checks for SLA violations."""
        report = run_disruption_simulation(
            baseline_routes=[self.route_1, self.route_2],
            scenario_type="traffic_surge",
            params={"delay_factor": 1.5, "added_minutes_per_route": 20.0},
            vehicle_specs=self.specs,
            depot=self.depot,
        )

        self.assertEqual(report.scenario_type, "traffic_surge")
        self.assertGreater(report.duration_minutes.simulated_value, report.duration_minutes.baseline_value)

    def test_simulation_dock_delay(self):
        """Simulation evaluates extended dwell time at loading dock."""
        report = run_disruption_simulation(
            baseline_routes=[self.route_1, self.route_2],
            scenario_type="dock_delay",
            params={"extra_dwell_minutes": 35.0, "stop_id": "s1"},
            vehicle_specs=self.specs,
            depot=self.depot,
        )

        self.assertEqual(report.scenario_type, "dock_delay")
        self.assertGreater(report.duration_minutes.simulated_value, report.duration_minutes.baseline_value)


if __name__ == "__main__":
    unittest.main()
