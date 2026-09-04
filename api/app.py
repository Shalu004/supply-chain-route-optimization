"""
REST API service for the route optimization engine.

Built with Flask because this sandbox has no internet access to install
FastAPI/OR-Tools. The route handlers below are intentionally thin and
framework-light (plain functions, dict in/out) so porting to FastAPI is
mechanical: swap `@app.route` + `request.get_json()` for `@app.post` +
a pydantic request model, and swap `jsonify()` for a `response_model`.
See docs/PORTING_TO_PRODUCTION.md for the exact steps and package pins.

Multi-tenancy note: this in-memory demo scopes optimization runs by
`company_id` to demonstrate the isolation pattern, but an in-memory dict
is NOT tenant isolation -- it's a single process with no persistence or
access control. Production tenant isolation belongs in the database
layer (PostgreSQL Row-Level Security), not application-level dict keys.
This is called out explicitly, not glossed over.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flask import Flask, jsonify, request

from routeopt.clustering import Stop
from routeopt.pipeline import CostModel, run_optimization
from schemas import ValidationError, parse_optimize_request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("routeopt.api")

app = Flask(__name__)

# In-memory run store, keyed by company_id -> list of run summaries.
# Demo/dev only -- replace with a database-backed store before any real use.
_RUN_STORE: dict[str, list[dict]] = {}


@app.route("/health", methods=["GET"])
def health():
    """Liveness check for load balancers / container orchestration."""
    return jsonify({"status": "ok"})


@app.route("/optimize", methods=["POST"])
def optimize():
    """
    Run the full clustering + routing pipeline for one company's delivery
    stops and return the optimized routes plus a cost comparison.
    """
    request_id = str(uuid.uuid4())[:8]
    start = time.monotonic()

    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    try:
        data = parse_optimize_request(payload)
    except ValidationError as e:
        logger.warning("request_id=%s validation_error=%s", request_id, str(e))
        return jsonify({"error": str(e)}), 422

    stops = [
        Stop(id=s["id"], lat=s["lat"], lon=s["lon"], demand=s.get("demand", 1.0))
        for s in data["stops"]
    ]
    depot = Stop(id="depot", **data["depot"]) if data["depot"] else None

    cost_kwargs = {}
    if data["cost_per_km"] is not None:
        cost_kwargs["cost_per_km"] = data["cost_per_km"]
    if data["cost_per_vehicle"] is not None:
        cost_kwargs["cost_per_vehicle"] = data["cost_per_vehicle"]
    cost_model = CostModel(**cost_kwargs)

    try:
        result = run_optimization(
            stops=stops,
            n_vehicles=data["vehicles"],
            vehicle_capacity=data["vehicle_capacity"],
            depot=depot,
            cost_model=cost_model,
        )
    except ValueError as e:
        logger.warning("request_id=%s engine_error=%s", request_id, str(e))
        return jsonify({"error": str(e)}), 422
    except Exception:
        logger.exception("request_id=%s unhandled_error", request_id)
        return jsonify({"error": "Internal error while optimizing routes"}), 500

    elapsed_ms = round((time.monotonic() - start) * 1000, 1)

    response = {
        "request_id": request_id,
        "company_id": data["company_id"],
        "routes": [
            {
                "zone_id": r.zone_id,
                "stop_ids": [s.id for s in r.stops],
                "distance_km": r.total_distance_km,
            }
            for r in result.routes
        ],
        "summary": {
            "total_distance_km": result.total_distance_km,
            "total_cost": result.total_cost,
            "vehicles_used": result.vehicles_used,
            "baseline_distance_km": result.baseline_distance_km,
            "baseline_cost": result.baseline_cost,
            "cost_reduction_pct": result.cost_reduction_pct,
        },
        "elapsed_ms": elapsed_ms,
    }

    _RUN_STORE.setdefault(data["company_id"], []).append(
        {"request_id": request_id, "summary": response["summary"]}
    )

    logger.info(
        "request_id=%s company_id=%s stops=%d vehicles=%d reduction_pct=%s elapsed_ms=%s",
        request_id,
        data["company_id"],
        len(stops),
        data["vehicles"],
        result.cost_reduction_pct,
        elapsed_ms,
    )

    return jsonify(response), 200


@app.route("/companies/<company_id>/runs", methods=["GET"])
def list_runs(company_id: str):
    """Return past optimization run summaries for one company (demo store)."""
    return jsonify({"company_id": company_id, "runs": _RUN_STORE.get(company_id, [])})


@app.errorhandler(404)
def not_found(_e):
    return jsonify({"error": "Not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
