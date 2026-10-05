"""
Distance Matrix Provider Abstraction for RouteOpt.

Provides a pluggable interface for computing pairwise distance matrices
between delivery stops using Haversine (spherical) or OSRM (real road networks).
"""

from __future__ import annotations

import abc
import json
import logging
import os
import urllib.request
from typing import Sequence

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


def get_distance_provider(provider_name: str = "haversine") -> AbstractDistanceProvider:
    """Factory function to retrieve distance matrix provider instance."""
    normalized = provider_name.lower().strip()
    if normalized == "osrm":
        return OSRMDistanceProvider()
    return HaversineDistanceProvider()
