"""
Distance Matrix Provider Abstraction for RouteOpt.

Provides a pluggable interface for computing pairwise distance matrices
between delivery stops using Haversine (spherical) or OSRM (real road networks),
with optional Redis caching for high-performance reuse.
"""

from __future__ import annotations

import abc
import hashlib
import json
import logging
import os
import urllib.request
from typing import Sequence, Any

import numpy as np

from .clustering import Stop

logger = logging.getLogger("routeopt.distance")

EARTH_RADIUS_KM = 6371.0


class AbstractDistanceProvider(abc.ABC):
    """Abstract base class for distance matrix providers."""

    @abc.abstractmethod
    def get_distance_matrix(self, stops: Sequence[Stop]) -> np.ndarray:
        """
        Compute an N x N distance matrix in kilometers for the given stops.

        Args:
            stops: sequence of Stop objects.

        Returns:
            N x N numpy array of pairwise distances in km.
        """
        pass


class HaversineDistanceProvider(AbstractDistanceProvider):
    """Calculates pairwise great-circle Haversine distances in kilometers."""

    def get_distance_matrix(self, stops: Sequence[Stop]) -> np.ndarray:
        if not stops:
            return np.zeros((0, 0))

        lat = np.radians(np.array([s.lat for s in stops]))
        lon = np.radians(np.array([s.lon for s in stops]))

        dlat = lat[:, None] - lat[None, :]
        dlon = lon[:, None] - lon[None, :]

        a = (
            np.sin(dlat / 2.0) ** 2
            + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2.0) ** 2
        )
        c = 2 * np.arcsin(np.clip(np.sqrt(a), -1, 1))
        return EARTH_RADIUS_KM * c


class OSRMDistanceProvider(AbstractDistanceProvider):
    """
    Fetches real road-network distance matrix from Open Source Routing Machine (OSRM).

    Falls back to HaversineDistanceProvider if OSRM server is unreachable or fails.
    """

    def __init__(self, server_url: str | None = None, timeout_seconds: float = 3.0):
        self.server_url = (
            server_url
            or os.environ.get("OSRM_SERVER_URL")
            or "http://router.project-osrm.org"
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._fallback = HaversineDistanceProvider()

    def get_distance_matrix(self, stops: Sequence[Stop]) -> np.ndarray:
        if not stops:
            return np.zeros((0, 0))
        if len(stops) == 1:
            return np.zeros((1, 1))

        # Format coordinates string: lon1,lat1;lon2,lat2;...
        coords_str = ";".join(f"{s.lon},{s.lat}" for s in stops)
        url = f"{self.server_url}/table/v1/driving/{coords_str}?annotations=distance"

        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "RouteOpt/1.0 Engine"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("code") == "Ok" and "distances" in data:
                        raw_distances_m = np.array(data["distances"], dtype=float)
                        # OSRM returns distances in meters; convert to kilometers
                        return raw_distances_m / 1000.0

            logger.warning(
                "OSRM response code not Ok or missing distances; falling back to Haversine."
            )
        except Exception as e:
            logger.warning("OSRM request failed (%s); falling back to Haversine.", e)

        return self._fallback.get_distance_matrix(stops)


class RedisCachedDistanceProvider(AbstractDistanceProvider):
    """
    Wrapper that caches distance matrices computed by an inner provider in Redis.
    If Redis is unavailable, it gracefully degrades to uncached evaluation.
    """

    def __init__(
        self,
        inner_provider: AbstractDistanceProvider,
        redis_client: Any | None = None,
        redis_url: str | None = None,
        ttl_seconds: int = 86400,
    ):
        self.inner_provider = inner_provider
        self.ttl_seconds = ttl_seconds
        self._redis = redis_client
        self._redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    def _get_client(self):
        if self._redis is not None:
            return self._redis
        try:
            import redis
            self._redis = redis.Redis.from_url(self._redis_url, socket_timeout=1.0)
            return self._redis
        except Exception as e:
            logger.debug("Failed to connect to Redis for matrix caching: %s", e)
            return None

    def _build_cache_key(self, stops: Sequence[Stop]) -> str:
        provider_name = self.inner_provider.__class__.__name__
        coords = ";".join(f"{round(s.lat, 6)},{round(s.lon, 6)}" for s in stops)
        raw_key = f"{provider_name}:{coords}"
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        return f"dist_matrix:{digest}"

    def get_distance_matrix(self, stops: Sequence[Stop]) -> np.ndarray:
        if not stops:
            return np.zeros((0, 0))

        key = self._build_cache_key(stops)
        client = self._get_client()

        if client is not None:
            try:
                cached_data = client.get(key)
                if cached_data is not None:
                    if isinstance(cached_data, bytes):
                        cached_data = cached_data.decode("utf-8")
                    matrix_list = json.loads(cached_data)
                    logger.info("Distance matrix cache HIT for key %s", key[:16])
                    return np.array(matrix_list, dtype=float)
            except Exception as e:
                logger.warning("Error reading from Redis cache: %s", e)

        # Cache miss or Redis error -> compute matrix using inner provider
        matrix = self.inner_provider.get_distance_matrix(stops)

        if client is not None:
            try:
                serialized = json.dumps(matrix.tolist())
                client.set(key, serialized, ex=self.ttl_seconds)
                logger.info("Cached distance matrix for key %s (ttl=%ds)", key[:16], self.ttl_seconds)
            except Exception as e:
                logger.warning("Error writing distance matrix to Redis cache: %s", e)

        return matrix


def get_distance_provider(
    provider_name: str = "haversine",
    use_cache: bool = False,
    redis_client: Any | None = None,
    redis_url: str | None = None,
) -> AbstractDistanceProvider:
    """Factory function to retrieve distance matrix provider instance with optional Redis caching."""
    normalized = provider_name.lower().strip()
    if normalized == "osrm":
        provider = OSRMDistanceProvider()
    else:
        provider = HaversineDistanceProvider()

    if use_cache:
        return RedisCachedDistanceProvider(
            inner_provider=provider,
            redis_client=redis_client,
            redis_url=redis_url,
        )

    return provider
