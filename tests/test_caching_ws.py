"""
Integration tests for Redis distance matrix caching and WebSockets real-time optimization stream.
"""

import sys
import unittest
from pathlib import Path

import fakeredis
import numpy as np
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from main import app, manager
from routeopt.clustering import Stop
from routeopt.distance import (
    HaversineDistanceProvider,
    RedisCachedDistanceProvider,
)


def make_stops(n: int = 3) -> list[Stop]:
    return [
        Stop(id=f"stop_{i}", lat=28.60 + i * 0.01, lon=77.20 + i * 0.01)
        for i in range(n)
    ]


class TestRedisCachingAndWebSockets(unittest.TestCase):
    def setUp(self):
        self.fake_redis = fakeredis.FakeRedis()

    def test_redis_cached_distance_provider(self):
        stops = make_stops(3)
        inner = HaversineDistanceProvider()
        cached_provider = RedisCachedDistanceProvider(
            inner_provider=inner,
            redis_client=self.fake_redis,
            ttl_seconds=3600,
        )

        # First call -> Cache MISS
        matrix1 = cached_provider.get_distance_matrix(stops)
        self.assertEqual(matrix1.shape, (3, 3))

        # Check key stored in Redis
        keys = self.fake_redis.keys("dist_matrix:*")
        self.assertEqual(len(keys), 1)

        # Second call -> Cache HIT
        matrix2 = cached_provider.get_distance_matrix(stops)
        np.testing.assert_array_almost_equal(matrix1, matrix2)

    def test_websocket_progress_stream(self):
        client = TestClient(app)
        job_id = "test-ws-job-123"

        with client.websocket_connect(f"/ws/optimize/{job_id}") as websocket:
            # Initial connection message
            data = websocket.receive_json()
            self.assertEqual(data["status"], "CONNECTED")
            self.assertEqual(data["job_id"], job_id)

            # Trigger a broadcast via manager
            manager.broadcast_sync(job_id, {
                "job_id": job_id,
                "status": "RUNNING",
                "progress_pct": 50,
                "message": "Computing matrix...",
            })

            msg = websocket.receive_json()
            self.assertEqual(msg["status"], "RUNNING")
            self.assertEqual(msg["progress_pct"], 50)


if __name__ == "__main__":
    unittest.main()
