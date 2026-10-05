"""
Test suite for distance matrix providers (Haversine & OSRM road network routing).
"""

import unittest
from unittest.mock import patch
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from routeopt.clustering import Stop
from routeopt.distance import (
    HaversineDistanceProvider,
    OSRMDistanceProvider,
    get_distance_provider,
)
from routeopt.pipeline import run_optimization


def make_stops(n: int = 4) -> list[Stop]:
    return [
        Stop(id=f"s_{i}", lat=28.60 + i * 0.01, lon=77.20 + i * 0.01)
        for i in range(n)
    ]


class TestDistanceProviders(unittest.TestCase):
    def test_haversine_provider_matrix_shape_and_symmetry(self):
        stops = make_stops(4)
        provider = HaversineDistanceProvider()
        matrix = provider.get_distance_matrix(stops)
        
        self.assertEqual(matrix.shape, (4, 4))
        self.assertAlmostEqual(matrix[0, 0], 0.0)
        self.assertAlmostEqual(matrix[0, 1], matrix[1, 0], places=5)
        self.assertGreater(matrix[0, 1], 0.0)

    def test_factory_resolution(self):
        p1 = get_distance_provider("haversine")
        p2 = get_distance_provider("osrm")
        self.assertIsInstance(p1, HaversineDistanceProvider)
        self.assertIsInstance(p2, OSRMDistanceProvider)

    def test_osrm_provider_fallback_on_network_error(self):
        stops = make_stops(3)
        # Point to invalid server to trigger network fallback to Haversine
        provider = OSRMDistanceProvider(server_url="http://invalid-osrm-host.local", timeout_seconds=0.1)
        matrix = provider.get_distance_matrix(stops)
        
        # Verify fallback produced valid distance matrix
        self.assertEqual(matrix.shape, (3, 3))
        self.assertGreater(matrix[0, 1], 0.0)

    def test_pipeline_integration(self):
        stops = make_stops(5)
        res = run_optimization(
            stops=stops,
            n_vehicles=2,
            vehicle_capacity=5.0,
            distance_provider="haversine",
        )
        self.assertEqual(res.distance_provider_used, "haversine")
        self.assertGreater(res.total_distance_km, 0.0)


if __name__ == "__main__":
    unittest.main()
