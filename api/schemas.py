"""
Request/response validation for the optimization API.

Kept dependency-free (no pydantic in this sandbox build) but structured
so migrating to pydantic models under FastAPI later is a near 1:1 port --
same field names, same validation rules, same error messages.
"""

from __future__ import annotations


class ValidationError(Exception):
    """Raised when incoming request data fails validation."""


REQUIRED_STOP_FIELDS = {"id", "lat", "lon"}


def parse_optimize_request(payload: dict) -> dict:
    """
    Validate and normalize a POST /optimize request body.

    Expected shape:
    {
        "company_id": "acme-corp",          # required, tenant identifier
        "vehicles": 3,                       # required, int >= 1
        "vehicle_capacity": 20,              # required, number > 0
        "depot": {"lat": 28.6, "lon": 77.2}, # optional
        "stops": [
            {"id": "s1", "lat": 28.61, "lon": 77.21, "demand": 1}, ...
        ],
        "cost_per_km": 0.9,                  # optional, defaults applied server-side
        "cost_per_vehicle": 50               # optional
    }

    Raises:
        ValidationError: with a human-readable message on any bad input.
    """
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object")

    company_id = payload.get("company_id")
    if not company_id or not isinstance(company_id, str):
        raise ValidationError("`company_id` is required and must be a string")

    vehicles = payload.get("vehicles")
    if not isinstance(vehicles, int) or vehicles < 1:
        raise ValidationError("`vehicles` is required and must be an integer >= 1")

    capacity = payload.get("vehicle_capacity")
    if not isinstance(capacity, (int, float)) or capacity <= 0:
        raise ValidationError("`vehicle_capacity` is required and must be a positive number")

    stops = payload.get("stops")
    if not isinstance(stops, list) or len(stops) == 0:
        raise ValidationError("`stops` is required and must be a non-empty list")

    for i, s in enumerate(stops):
        if not isinstance(s, dict) or not REQUIRED_STOP_FIELDS.issubset(s.keys()):
            raise ValidationError(
                f"stops[{i}] must contain 'id', 'lat', and 'lon'"
            )
        if not isinstance(s["lat"], (int, float)) or not (-90 <= s["lat"] <= 90):
            raise ValidationError(f"stops[{i}].lat must be a number in [-90, 90]")
        if not isinstance(s["lon"], (int, float)) or not (-180 <= s["lon"] <= 180):
            raise ValidationError(f"stops[{i}].lon must be a number in [-180, 180]")

    if vehicles > len(stops):
        raise ValidationError(
            f"`vehicles` ({vehicles}) cannot exceed number of stops ({len(stops)})"
        )

    depot = payload.get("depot")
    if depot is not None:
        if not isinstance(depot, dict) or "lat" not in depot or "lon" not in depot:
            raise ValidationError("`depot`, if provided, must have 'lat' and 'lon'")

    return {
        "company_id": company_id,
        "vehicles": vehicles,
        "vehicle_capacity": float(capacity),
        "stops": stops,
        "depot": depot,
        "cost_per_km": payload.get("cost_per_km"),
        "cost_per_vehicle": payload.get("cost_per_vehicle"),
    }
