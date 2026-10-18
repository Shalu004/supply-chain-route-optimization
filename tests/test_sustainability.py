"""
Test suite for RouteOpt Sustainability and Multi-Objective Evaluation.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routeopt.clustering import Stop
from routeopt.routing import Route
from routeopt.sustainability import (
    EmissionFactors,
    MultiObjectiveWeights,
    evaluate_sustainability,
)


class TestSustainabilityEvaluation(unittest.TestCase):
    def setUp(self):
        self.stop_depot = Stop(id="depot", lat=28.60, lon=77.20)
        self.stop_1 = Stop(id="s1", lat=28.65, lon=77.25, demand=2.0)
        self.stop_2 = Stop(id="s2", lat=28.70, lon=77.30, demand=3.0)

        self.mock_route_1 = Route(
            zone_id=0,
            stops=[self.stop_depot, self.stop_1, self.stop_depot],
            total_distance_km=50.0,
            total_duration_minutes=90.0,
            vehicle_id="v_van_1",
            vehicle_name="Van 1",
        )
        self.mock_route_2 = Route(
            zone_id=1,
            stops=[self.stop_depot, self.stop_2, self.stop_depot],
            total_distance_km=70.0,
            total_duration_minutes=120.0,
            vehicle_id="v_ev_2",
            vehicle_name="Electric Van 2",
        )

    def test_diesel_fleet_sustainability(self):
        """Test sustainability metrics under default diesel fleet."""
        routes = [self.mock_route_1]
        assessment = evaluate_sustainability(routes, fuel_type="diesel")

        self.assertEqual(assessment.vehicles_active, 1)
        self.assertEqual(assessment.total_distance_km, 50.0)
        self.assertEqual(assessment.total_duration_minutes, 90.0)

        # 50 km * 11.5 L / 100km = 5.75 liters
        self.assertAlmostEqual(assessment.fuel_consumption_liters, 5.75, places=2)
        # 5.75 L * 2.68 kg CO2/L = 15.41 kg CO2
        self.assertAlmostEqual(assessment.total_co2_emissions_kg, 15.41, places=2)
        # Positive operating costs
        self.assertTrue(assessment.total_operating_cost_usd > 0)
        self.assertTrue(0 <= assessment.composite_sustainability_score <= 100)

    def test_electric_vehicle_fleet_emissions(self):
        """Electric fleet has lower CO2 emissions than diesel for the same route distance."""
        routes = [self.mock_route_1]
        diesel_res = evaluate_sustainability(routes, fuel_type="diesel")
        ev_res = evaluate_sustainability(routes, fuel_type="electric")

        # EV has 0 liquid fuel and uses kWh
        self.assertEqual(ev_res.fuel_consumption_liters, 0.0)
        self.assertTrue(ev_res.electricity_consumption_kwh > 0)

        # 50 km * 28 kWh/100km = 14 kWh. 14 * 0.385 = 5.39 kg CO2 vs diesel 15.41 kg CO2
        self.assertLess(ev_res.total_co2_emissions_kg, diesel_res.total_co2_emissions_kg)

    def test_heterogeneous_fleet_fuel_types(self):
        """Routes with mixed diesel and electric vehicles."""
        routes = [self.mock_route_1, self.mock_route_2]
        mapping = {"v_van_1": "diesel", "v_ev_2": "electric"}
        assessment = evaluate_sustainability(routes, vehicle_fuel_types=mapping)

        self.assertEqual(assessment.vehicles_active, 2)
        self.assertTrue(assessment.fuel_consumption_liters > 0)
        self.assertTrue(assessment.electricity_consumption_kwh > 0)
        self.assertEqual(len(assessment.per_route_metrics), 2)
        self.assertEqual(assessment.per_route_metrics[0].fuel_type, "diesel")
        self.assertEqual(assessment.per_route_metrics[1].fuel_type, "electric")

    def test_multi_objective_custom_weights(self):
        """Custom weight balance behaves predictably."""
        weights = MultiObjectiveWeights(weight_distance=0.1, weight_time=0.1, weight_cost=0.1, weight_emissions=0.7)
        assessment = evaluate_sustainability([self.mock_route_1], weights=weights)

        self.assertAlmostEqual(sum(assessment.weights_used.values()), 1.0, places=2)
        self.assertAlmostEqual(assessment.weights_used["weight_emissions"], 0.7, places=2)


if __name__ == "__main__":
    unittest.main()
