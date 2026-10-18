"""
RouteOpt Sustainability & Multi-Objective Evaluation Engine.

Evaluates supply chain logistics across economic and environmental dimensions:
- Distance (km)
- Travel & service duration (minutes)
- Fuel / Energy consumption (liters or kWh)
- Greenhouse gas emissions (kg CO2 equivalent)
- Operating costs (dispatch, distance wear, fuel, driver labor)
- Composite multi-objective sustainability index
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


FuelType = Literal["diesel", "gasoline", "electric", "hybrid"]


@dataclass
class EmissionFactors:
    """
    Standard GHG emission and fuel consumption parameters.
    Default parameters based on EPA & EEA freight transport standards.
    """
    # Consumption per 100 km (liters for combustion, kWh for EV)
    consumption_per_100km: dict[str, float] = field(
        default_factory=lambda: {
            "diesel": 11.5,
            "gasoline": 10.0,
            "electric": 28.0,
            "hybrid": 6.5,
        }
    )
    # Emission factor (kg CO2 per liter or per kWh)
    co2_factor_per_unit: dict[str, float] = field(
        default_factory=lambda: {
            "diesel": 2.68,     # 2.68 kg CO2/L diesel
            "gasoline": 2.31,   # 2.31 kg CO2/L gasoline
            "electric": 0.385,  # 0.385 kg CO2/kWh (average regional electricity grid)
            "hybrid": 2.31,
        }
    )
    # Unit prices ($/L or $/kWh)
    energy_price_per_unit: dict[str, float] = field(
        default_factory=lambda: {
            "diesel": 1.55,
            "gasoline": 1.45,
            "electric": 0.18,
            "hybrid": 1.45,
        }
    )
    driver_hourly_wage: float = 24.0          # USD / hour
    vehicle_maintenance_per_km: float = 0.15  # USD / km
    carbon_cost_per_metric_ton: float = 50.0  # USD / metric ton CO2 (.05 / kg)


@dataclass
class MultiObjectiveWeights:
    """Configurable weights for the composite evaluation objective."""
    weight_distance: float = 0.25
    weight_time: float = 0.25
    weight_cost: float = 0.25
    weight_emissions: float = 0.25

    def __post_init__(self):
        total = self.weight_distance + self.weight_time + self.weight_cost + self.weight_emissions
        if total <= 0:
            raise ValueError("Sum of multi-objective weights must be > 0")
        # Normalize weights to sum to 1.0
        self.weight_distance /= total
        self.weight_time /= total
        self.weight_cost /= total
        self.weight_emissions /= total


@dataclass
class RouteSustainabilityMetric:
    """Sustainability breakdown for an individual vehicle route."""
    vehicle_id: str
    fuel_type: str
    distance_km: float
    duration_minutes: float
    energy_consumed: float          # liters or kWh
    energy_unit: str                # "liters" or "kWh"
    co2_emissions_kg: float
    fuel_cost: float
    labor_cost: float
    maintenance_cost: float
    total_route_cost: float


@dataclass
class SustainabilityAssessment:
    """Fleet-wide sustainability and multi-objective impact assessment."""
    total_distance_km: float
    total_duration_minutes: float
    vehicles_active: int
    fuel_consumption_liters: float  # Total liquid fuel (diesel/gasoline/hybrid)
    electricity_consumption_kwh: float  # Total EV grid draw
    total_co2_emissions_kg: float
    carbon_offset_cost_usd: float
    total_fuel_cost_usd: float
    total_labor_cost_usd: float
    total_maintenance_cost_usd: float
    total_fixed_dispatch_cost_usd: float
    total_operating_cost_usd: float
    composite_sustainability_score: float  # 0 to 100, where 100 is optimal/highest efficiency
    per_route_metrics: list[RouteSustainabilityMetric]
    weights_used: dict[str, float]


def evaluate_sustainability(
    routes: list,
    fuel_type: FuelType = "diesel",
    factors: EmissionFactors | None = None,
    weights: MultiObjectiveWeights | None = None,
    fixed_cost_per_vehicle: float = 50.0,
    vehicle_fuel_types: dict[str, FuelType] | None = None,
) -> SustainabilityAssessment:
    """
    Evaluate sustainability metrics and composite cost for a given set of routes.

    Args:
        routes: list of Route objects.
        fuel_type: default fleet fuel type.
        factors: custom emission and pricing factors.
        weights: multi-objective weights.
        fixed_cost_per_vehicle: vehicle fixed dispatch cost.
        vehicle_fuel_types: optional per-vehicle fuel type mapping.

    Returns:
        SustainabilityAssessment with full environmental and financial breakdown.
    """
    factors = factors or EmissionFactors()
    weights = weights or MultiObjectiveWeights()
    vehicle_fuel_types = vehicle_fuel_types or {}

    total_dist = 0.0
    total_dur = 0.0
    total_fuel_l = 0.0
    total_elec_kwh = 0.0
    total_co2 = 0.0
    total_fuel_cost = 0.0
    total_labor_cost = 0.0
    total_maint_cost = 0.0
    per_route_metrics: list[RouteSustainabilityMetric] = []

    for r in routes:
        v_id = getattr(r, "vehicle_id", None) or f"v_{r.zone_id}"
        v_fuel = vehicle_fuel_types.get(v_id, fuel_type)

        dist_km = float(getattr(r, "total_distance_km", 0.0))
        dur_min = float(getattr(r, "total_duration_minutes", 0.0))
        if dur_min <= 0 and dist_km > 0:
            # Fallback estimation at 30 km/h + 5 min per stop
            num_stops = max(0, len(r.stops) - 2)
            dur_min = (dist_km / 30.0) * 60.0 + (num_stops * 5.0)

        rate = factors.consumption_per_100km.get(v_fuel, 11.5)
        energy_amount = (dist_km / 100.0) * rate
        unit = "kWh" if v_fuel == "electric" else "liters"

        if v_fuel == "electric":
            total_elec_kwh += energy_amount
        else:
            total_fuel_l += energy_amount

        co2_factor = factors.co2_factor_per_unit.get(v_fuel, 2.68)
        co2_kg = energy_amount * co2_factor
        total_co2 += co2_kg

        unit_price = factors.energy_price_per_unit.get(v_fuel, 1.55)
        fuel_cost = energy_amount * unit_price
        labor_cost = (dur_min / 60.0) * factors.driver_hourly_wage
        maint_cost = dist_km * factors.vehicle_maintenance_per_km
        route_cost = fuel_cost + labor_cost + maint_cost + fixed_cost_per_vehicle

        total_dist += dist_km
        total_dur += dur_min
        total_fuel_cost += fuel_cost
        total_labor_cost += labor_cost
        total_maint_cost += maint_cost

        per_route_metrics.append(
            RouteSustainabilityMetric(
                vehicle_id=v_id,
                fuel_type=v_fuel,
                distance_km=round(dist_km, 2),
                duration_minutes=round(dur_min, 1),
                energy_consumed=round(energy_amount, 2),
                energy_unit=unit,
                co2_emissions_kg=round(co2_kg, 2),
                fuel_cost=round(fuel_cost, 2),
                labor_cost=round(labor_cost, 2),
                maintenance_cost=round(maint_cost, 2),
                total_route_cost=round(route_cost, 2),
            )
        )

    active_vehicles = len(routes)
    fixed_dispatch_cost = active_vehicles * fixed_cost_per_vehicle
    total_operating_cost = total_fuel_cost + total_labor_cost + total_maint_cost + fixed_dispatch_cost
    carbon_offset_cost = (total_co2 / 1000.0) * factors.carbon_cost_per_metric_ton

    # Composite Sustainability Score (0 - 100)
    # Higher score = more efficient (penalized by high emissions, distance, time, cost)
    baseline_dist_ref = max(total_dist, 10.0)
    baseline_co2_ref = max(total_co2, 1.0)
    score = 100.0 - min(
        90.0,
        (
            weights.weight_distance * (total_dist / baseline_dist_ref * 20.0)
            + weights.weight_time * (total_dur / max(total_dur, 60.0) * 20.0)
            + weights.weight_cost * (total_operating_cost / max(total_operating_cost, 50.0) * 20.0)
            + weights.weight_emissions * (total_co2 / baseline_co2_ref * 20.0)
        ),
    )

    return SustainabilityAssessment(
        total_distance_km=round(total_dist, 2),
        total_duration_minutes=round(total_dur, 1),
        vehicles_active=active_vehicles,
        fuel_consumption_liters=round(total_fuel_l, 2),
        electricity_consumption_kwh=round(total_elec_kwh, 2),
        total_co2_emissions_kg=round(total_co2, 2),
        carbon_offset_cost_usd=round(carbon_offset_cost, 2),
        total_fuel_cost_usd=round(total_fuel_cost, 2),
        total_labor_cost_usd=round(total_labor_cost, 2),
        total_maintenance_cost_usd=round(total_maint_cost, 2),
        total_fixed_dispatch_cost_usd=round(fixed_dispatch_cost, 2),
        total_operating_cost_usd=round(total_operating_cost, 2),
        composite_sustainability_score=round(score, 1),
        per_route_metrics=per_route_metrics,
        weights_used={
            "weight_distance": round(weights.weight_distance, 3),
            "weight_time": round(weights.weight_time, 3),
            "weight_cost": round(weights.weight_cost, 3),
            "weight_emissions": round(weights.weight_emissions, 3),
        },
    )
