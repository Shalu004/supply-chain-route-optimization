"""
RouteOpt Digital Twin & Disruption Simulator.

Runs controlled 'what-if' logistics stress tests:
- Vehicle breakdown mid-shift
- On-demand rush order arrival
- Traffic congestion surges
- Extended warehouse / customer dock dwell times

Compares baseline plan vs adapted plan and produces a measurable KPI delta report:
- Total distance & duration deltas
- Operating cost & carbon emission impacts
- SLA time-window violations
- Unserved orders count
- Solver response runtime
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .clustering import Stop, VehicleSpec
from .distance import AbstractDistanceProvider, HaversineDistanceProvider
from .dynamic import (
    reoptimize_cancel_order,
    reoptimize_insert_order,
    reoptimize_traffic_delay,
    reoptimize_vehicle_breakdown,
)
from .routing import Route, _route_length
from .sustainability import evaluate_sustainability

logger = logging.getLogger("routeopt.simulation")


@dataclass
class ScenarioKPIDelta:
    baseline_value: float
    simulated_value: float
    absolute_delta: float
    percentage_delta: float


@dataclass
class SimulationReport:
    scenario_name: str
    scenario_type: str
    description: str
    distance_km: ScenarioKPIDelta
    duration_minutes: ScenarioKPIDelta
    operating_cost_usd: ScenarioKPIDelta
    co2_emissions_kg: ScenarioKPIDelta
    vehicles_used: ScenarioKPIDelta
    sla_violations_count: int
    unserved_orders_count: int
    execution_time_seconds: float
    baseline_routes: list[dict]
    simulated_routes: list[dict]
    unserved_orders: list[dict]
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def run_disruption_simulation(
    baseline_routes: list[Route],
    scenario_type: str,
    params: dict[str, Any],
    vehicle_specs: list[VehicleSpec],
    depot: Stop | None = None,
    completed_stop_ids: set[str] | None = None,
    distance_provider: AbstractDistanceProvider | None = None,
    average_speed_kmh: float = 30.0,
) -> SimulationReport:
    """
    Execute a digital twin disruption simulation against current baseline routes.
    Simulations are isolated and do not alter live production state.
    """
    t_start = time.monotonic()
    provider = distance_provider or HaversineDistanceProvider()
    completed_ids = completed_stop_ids or set()

    # 1. Evaluate baseline sustainability & economics
    base_sustain = evaluate_sustainability(baseline_routes)
    base_dist = base_sustain.total_distance_km
    base_dur = base_sustain.total_duration_minutes
    base_cost = base_sustain.total_operating_cost_usd
    base_co2 = base_sustain.total_co2_emissions_kg
    base_vehicles = base_sustain.vehicles_active

    simulated_routes: list[Route] = list(baseline_routes)
    unserved_orders: list[dict] = []
    scenario_desc = ""

    # 2. Apply disruption according to scenario type
    if scenario_type == "vehicle_breakdown":
        target_v_id = params.get("vehicle_id")
        if not target_v_id and baseline_routes:
            target_v_id = getattr(baseline_routes[0], "vehicle_id", None) or f"v_{baseline_routes[0].zone_id}"
        scenario_desc = f"Simulated mechanical failure of vehicle '{target_v_id}' mid-route"

        res = reoptimize_vehicle_breakdown(
            active_routes=baseline_routes,
            broken_vehicle_id=target_v_id,
            vehicle_specs=vehicle_specs,
            depot=depot,
            completed_stop_ids=completed_ids,
            distance_provider=provider,
            average_speed_kmh=average_speed_kmh,
        )
        simulated_routes = res.routes
        unserved_orders = [{"stop_id": u.stop_id, "demand": u.demand, "reason": u.reason} for u in res.unassigned_stops]

    elif scenario_type == "emergency_order":
        new_stop = Stop(
            id=params.get("id", "rush-order-1"),
            lat=float(params.get("lat", 28.62)),
            lon=float(params.get("lon", 77.22)),
            demand=float(params.get("demand", 2.0)),
            time_window=tuple(params.get("time_window")) if params.get("time_window") else None,
            service_duration=float(params.get("service_duration", 10.0)),
        )
        scenario_desc = f"High-priority on-demand order arrival ({new_stop.id}, demand {new_stop.demand})"
        res = reoptimize_insert_order(
            active_routes=baseline_routes,
            new_stop=new_stop,
            vehicle_specs=vehicle_specs,
            depot=depot,
            completed_stop_ids=completed_ids,
            distance_provider=provider,
            average_speed_kmh=average_speed_kmh,
        )
        simulated_routes = res.routes
        unserved_orders = [{"stop_id": u.stop_id, "demand": u.demand, "reason": u.reason} for u in res.unassigned_stops]

    elif scenario_type == "traffic_surge":
        delay_factor = float(params.get("delay_factor", 1.5))
        added_delay = float(params.get("added_minutes_per_route", 25.0))
        target_v_id = params.get("vehicle_id")
        scenario_desc = f"Traffic congestion surge: +{added_delay} min route delay on fleet corridor"

        new_routes = []
        for r in baseline_routes:
            v_id = getattr(r, "vehicle_id", None) or f"v_{r.zone_id}"
            if not target_v_id or v_id == target_v_id:
                new_dur = round(r.total_duration_minutes * delay_factor + added_delay, 1)
                new_routes.append(
                    Route(
                        zone_id=r.zone_id,
                        stops=r.stops,
                        total_distance_km=r.total_distance_km,
                        total_duration_minutes=new_dur,
                        vehicle_id=v_id,
                        vehicle_name=getattr(r, "vehicle_name", None),
                    )
                )
            else:
                new_routes.append(r)
        simulated_routes = new_routes

    elif scenario_type == "dock_delay":
        extra_dwell = float(params.get("extra_dwell_minutes", 30.0))
        target_stop_id = params.get("stop_id")
        scenario_desc = f"Extended dock loading delay: +{extra_dwell} minutes dwell at customer stop"

        new_routes = []
        for r in baseline_routes:
            has_stop = any(s.id == target_stop_id for s in r.stops) if target_stop_id else True
            if has_stop:
                new_dur = round(r.total_duration_minutes + extra_dwell, 1)
                new_routes.append(
                    Route(
                        zone_id=r.zone_id,
                        stops=r.stops,
                        total_distance_km=r.total_distance_km,
                        total_duration_minutes=new_dur,
                        vehicle_id=getattr(r, "vehicle_id", None),
                        vehicle_name=getattr(r, "vehicle_name", None),
                    )
                )
            else:
                new_routes.append(r)
        simulated_routes = new_routes

    else:
        raise ValueError(f"Unknown simulation scenario type '{scenario_type}'")

    # 3. Evaluate simulated sustainability & economics
    sim_sustain = evaluate_sustainability(simulated_routes)
    sim_dist = sim_sustain.total_distance_km
    sim_dur = sim_sustain.total_duration_minutes
    sim_cost = sim_sustain.total_operating_cost_usd
    sim_co2 = sim_sustain.total_co2_emissions_kg
    sim_vehicles = sim_sustain.vehicles_active

    # 4. Count SLA breaches (deliveries arriving later than their latest time window)
    km_per_min = max(average_speed_kmh / 60.0, 0.1)
    sla_violations = 0
    for r in simulated_routes:
        cumul_time = 0.0
        stops = r.stops
        if len(stops) >= 2:
            dist_mat = provider.get_distance_matrix(stops)
            for i in range(len(stops) - 1):
                cumul_time += dist_mat[i, i + 1] / km_per_min
                st = stops[i + 1]
                if st.time_window and cumul_time > st.time_window[1]:
                    sla_violations += 1
                cumul_time += st.service_duration

    def make_kpi(base: float, sim: float) -> ScenarioKPIDelta:
        diff = round(sim - base, 2)
        pct = round((diff / base * 100.0), 2) if base > 0 else 0.0
        return ScenarioKPIDelta(
            baseline_value=round(base, 2),
            simulated_value=round(sim, 2),
            absolute_delta=diff,
            percentage_delta=pct,
        )

    t_elapsed = round(time.monotonic() - t_start, 3)

    return SimulationReport(
        scenario_name=params.get("name", scenario_type.replace("_", " ").title()),
        scenario_type=scenario_type,
        description=scenario_desc,
        distance_km=make_kpi(base_dist, sim_dist),
        duration_minutes=make_kpi(base_dur, sim_dur),
        operating_cost_usd=make_kpi(base_cost, sim_cost),
        co2_emissions_kg=make_kpi(base_co2, sim_co2),
        vehicles_used=make_kpi(float(base_vehicles), float(sim_vehicles)),
        sla_violations_count=sla_violations,
        unserved_orders_count=len(unserved_orders),
        execution_time_seconds=t_elapsed,
        baseline_routes=[
            {
                "zone_id": r.zone_id,
                "vehicle_id": getattr(r, "vehicle_id", f"v_{r.zone_id}"),
                "stop_ids": [s.id for s in r.stops],
                "distance_km": r.total_distance_km,
                "duration_min": r.total_duration_minutes,
            }
            for r in baseline_routes
        ],
        simulated_routes=[
            {
                "zone_id": r.zone_id,
                "vehicle_id": getattr(r, "vehicle_id", f"v_{r.zone_id}"),
                "stop_ids": [s.id for s in r.stops],
                "distance_km": r.total_distance_km,
                "duration_min": r.total_duration_minutes,
            }
            for r in simulated_routes
        ],
        unserved_orders=unserved_orders,
    )
