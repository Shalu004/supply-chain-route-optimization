"""
FastAPI application for RouteOpt API service.
"""

import logging
import time
import uuid

import asyncio
from fastapi import Depends, FastAPI, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request

from routeopt.auth import create_access_token, decode_access_token, hash_password, verify_password
from routeopt.clustering import Stop, VehicleSpec
from routeopt.db.models import Company, OptimizationRun, RouteRecord, Vehicle
from routeopt.db.session import admin_session, scoped_session_for_company
from routeopt.pipeline import CostModel, run_optimization

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="RouteOpt API", version="1.0")
app.state.limiter = limiter


class ConnectionManager:
    """Manages live WebSocket connections for streaming real-time optimization updates."""

    def __init__(self):
        self.active_connections: dict[str, set[WebSocket]] = {}

    async def connect(self, job_id: str, websocket: WebSocket):
        await websocket.accept()
        if job_id not in self.active_connections:
            self.active_connections[job_id] = set()
        self.active_connections[job_id].add(websocket)

    def disconnect(self, job_id: str, websocket: WebSocket):
        if job_id in self.active_connections:
            self.active_connections[job_id].discard(websocket)
            if not self.active_connections[job_id]:
                del self.active_connections[job_id]

    async def broadcast(self, job_id: str, message: dict):
        if job_id in self.active_connections:
            for connection in list(self.active_connections[job_id]):
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

    def broadcast_sync(self, job_id: str, message: dict):
        if job_id and job_id in self.active_connections:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.broadcast(job_id, message))
            except RuntimeError:
                try:
                    asyncio.run(self.broadcast(job_id, message))
                except Exception:
                    pass
            except Exception:
                pass


manager = ConnectionManager()

@app.exception_handler(RateLimitExceeded)
def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# ---------- Pydantic schemas ----------

class RegisterRequest(BaseModel):
    company_slug: str = Field(..., min_length=2, max_length=64)
    company_name: str
    password: str = Field(..., min_length=8)


class StopIn(BaseModel):
    id: str
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    demand: float = 1.0
    time_window: list[float] | None = None
    service_duration: float = Field(0.0, ge=0)
    pickup_stop_id: str | None = None
    soft_time_window: list[float] | None = None
    early_penalty_cost: float = Field(0.0, ge=0)
    late_penalty_cost: float = Field(0.0, ge=0)

    @field_validator("time_window")
    @classmethod
    def validate_time_window(cls, v: list[float] | None) -> list[float] | None:
        if v is not None:
            if len(v) != 2:
                raise ValueError("time_window must be a list of exactly 2 numbers: [earliest, latest]")
            earliest, latest = v[0], v[1]
            if earliest < 0:
                raise ValueError(f"time_window earliest time ({earliest}) cannot be negative")
            if latest < earliest:
                raise ValueError(f"time_window latest time ({latest}) cannot be earlier than earliest time ({earliest})")
        return v

    @field_validator("soft_time_window")
    @classmethod
    def validate_soft_time_window(cls, v: list[float] | None) -> list[float] | None:
        if v is not None:
            if len(v) != 2:
                raise ValueError("soft_time_window must be a list of exactly 2 numbers: [earliest, latest]")
            earliest, latest = v[0], v[1]
            if earliest < 0:
                raise ValueError(f"soft_time_window earliest time ({earliest}) cannot be negative")
            if latest < earliest:
                raise ValueError(f"soft_time_window latest time ({latest}) cannot be earlier than earliest time ({earliest})")
        return v


class DepotIn(BaseModel):
    lat: float
    lon: float


class VehicleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    vehicle_type: str = "van"
    capacity: float = Field(20.0, gt=0)
    cost_per_km: float = Field(0.9, ge=0)
    fixed_cost: float = Field(50.0, ge=0)


class VehicleSpecIn(BaseModel):
    id: str
    name: str = "Vehicle"
    capacity: float = Field(20.0, gt=0)
    cost_per_km: float = Field(0.9, ge=0)
    fixed_cost: float = Field(50.0, ge=0)
    max_distance_km: float | None = Field(None, gt=0)


class OptimizeRequest(BaseModel):
    job_id: str | None = Field(None, description="Optional job ID for WebSocket progress tracking")
    use_cache: bool = Field(True, description="Enable Redis distance matrix caching")
    vehicles: int = Field(..., ge=1)
    vehicle_capacity: float = Field(..., gt=0)
    stops: list[StopIn] = Field(..., min_length=1)
    depot: DepotIn | None = None
    cost_per_km: float | None = None
    cost_per_vehicle: float | None = None
    solver_type: str = Field("ortools", description="Solver engine: 'ortools' or 'heuristic'")
    distance_provider: str = Field("haversine", description="Distance provider: 'haversine' or 'osrm'")
    vehicle_specs: list[VehicleSpecIn] | None = None
    max_route_distance_km: float | None = Field(None, gt=0)
    average_speed_kmh: float = Field(30.0, gt=0, description="Average fleet travel speed in km/h for travel time calculation")


# ---------- Auth dependency ----------

def get_current_company(token: str = Depends(oauth2_scheme)) -> dict:
    """Verifies the JWT and returns {company_id, company_slug}. Raises 401 if invalid."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        company_id: str = payload.get("sub")
        company_slug: str = payload.get("slug")
        if company_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return {"company_id": company_id, "company_slug": company_slug}


# ---------- Routes ----------


@app.get("/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws/optimize/{job_id}")
async def websocket_optimize(websocket: WebSocket, job_id: str):
    await manager.connect(job_id, websocket)
    try:
        await websocket.send_json({
            "job_id": job_id,
            "status": "CONNECTED",
            "progress_pct": 0,
            "message": "Connected to RouteOpt optimization event stream"
        })
        while True:
            # Keep connection alive until client disconnects
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(job_id, websocket)
    except Exception:
        manager.disconnect(job_id, websocket)



@app.post("/register", status_code=201)
@limiter.limit("30/minute")
def register(request: Request, body: RegisterRequest):
    with admin_session() as session:
        existing = session.query(Company).filter_by(slug=body.company_slug).first()
        if existing:
            raise HTTPException(status_code=409, detail="Company slug already registered")

        company = Company(
            slug=body.company_slug,
            name=body.company_name,
            hashed_password=hash_password(body.password),
        )
        session.add(company)
        session.flush()
        company_id = str(company.id)

    return {"company_id": company_id, "company_slug": body.company_slug}


@app.post("/token")
@limiter.limit("60/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 password flow: form_data.username holds the company_slug."""
    with admin_session() as session:
        company = session.query(Company).filter_by(slug=form_data.username).first()
        if not company or not company.hashed_password or not verify_password(
            form_data.password, company.hashed_password
        ):
            raise HTTPException(status_code=401, detail="Incorrect company slug or password")

        token = create_access_token(str(company.id), company.slug)

    return {"access_token": token, "token_type": "bearer"}


@app.post("/vehicles", status_code=201)
def create_vehicle(
    body: VehicleCreate,
    current_company: dict = Depends(get_current_company),
):
    company_id = current_company["company_id"]
    with scoped_session_for_company(company_id) as session:
        vehicle = Vehicle(
            company_id=company_id,
            name=body.name,
            vehicle_type=body.vehicle_type,
            capacity=body.capacity,
            cost_per_km=body.cost_per_km,
            fixed_cost=body.fixed_cost,
            is_active=True,
        )
        session.add(vehicle)
        session.flush()
        vehicle_id = str(vehicle.id)

    return {
        "vehicle_id": vehicle_id,
        "name": body.name,
        "vehicle_type": body.vehicle_type,
        "capacity": body.capacity,
        "cost_per_km": body.cost_per_km,
        "fixed_cost": body.fixed_cost,
    }


@app.get("/vehicles")
def list_vehicles(current_company: dict = Depends(get_current_company)):
    company_id = current_company["company_id"]
    with scoped_session_for_company(company_id) as session:
        vehicles = session.query(Vehicle).filter_by(company_id=company_id, is_active=True).all()
        return {
            "company_slug": current_company["company_slug"],
            "vehicles": [
                {
                    "id": str(v.id),
                    "name": v.name,
                    "vehicle_type": v.vehicle_type,
                    "capacity": float(v.capacity),
                    "cost_per_km": float(v.cost_per_km) if v.cost_per_km else 0.9,
                    "fixed_cost": float(v.fixed_cost) if v.fixed_cost else 50.0,
                }
                for v in vehicles
            ],
        }


@app.post("/optimize")
@limiter.limit("120/minute")
def optimize(
    request: Request,
    body: OptimizeRequest,
    current_company: dict = Depends(get_current_company),
):
    request_id = str(uuid.uuid4())[:8]
    start = time.monotonic()
    company_id = current_company["company_id"]

    if body.vehicles > len(body.stops):
        raise HTTPException(
            status_code=422,
            detail=f"vehicles ({body.vehicles}) cannot exceed number of stops ({len(body.stops)})",
        )

    # Validate Pickup and Delivery (PDP) pair references
    stop_ids_set = {s.id for s in body.stops}
    for s in body.stops:
        if s.pickup_stop_id:
            if s.pickup_stop_id == s.id:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid pickup_stop_id for stop '{s.id}': a stop cannot be its own pickup stop",
                )
            if s.pickup_stop_id not in stop_ids_set:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid pickup_stop_id '{s.pickup_stop_id}' for stop '{s.id}': referenced pickup stop ID does not exist in request stops",
                )

    stops = [
        Stop(
            id=s.id,
            lat=s.lat,
            lon=s.lon,
            demand=s.demand,
            time_window=tuple(s.time_window) if s.time_window and len(s.time_window) == 2 else None,
            service_duration=s.service_duration,
            pickup_stop_id=s.pickup_stop_id,
            soft_time_window=tuple(s.soft_time_window) if s.soft_time_window and len(s.soft_time_window) == 2 else None,
            early_penalty_cost=s.early_penalty_cost,
            late_penalty_cost=s.late_penalty_cost,
        )
        for s in body.stops
    ]
    depot = Stop(id="depot", lat=body.depot.lat, lon=body.depot.lon) if body.depot else None

    vehicle_specs = (
        [
            VehicleSpec(
                id=vs.id,
                name=vs.name,
                capacity=vs.capacity,
                cost_per_km=vs.cost_per_km,
                fixed_cost=vs.fixed_cost,
                max_distance_km=vs.max_distance_km,
            )
            for vs in body.vehicle_specs
        ]
        if body.vehicle_specs
        else None
    )

    cost_kwargs = {}
    if body.cost_per_km is not None:
        cost_kwargs["cost_per_km"] = body.cost_per_km
    if body.cost_per_vehicle is not None:
        cost_kwargs["cost_per_vehicle"] = body.cost_per_vehicle
    cost_model = CostModel(**cost_kwargs)

    job_id = body.job_id or request_id
    manager.broadcast_sync(job_id, {
        "job_id": job_id,
        "status": "RUNNING",
        "progress_pct": 25,
        "message": "Parsing vehicle fleet specs and computing distance matrix..."
    })

    try:
        result = run_optimization(
            stops=stops,
            n_vehicles=body.vehicles,
            vehicle_capacity=body.vehicle_capacity,
            depot=depot,
            cost_model=cost_model,
            solver_type=body.solver_type,
            distance_provider=body.distance_provider,
            vehicle_specs=vehicle_specs,
            max_route_distance_km=body.max_route_distance_km,
            use_cache=body.use_cache,
            average_speed_kmh=body.average_speed_kmh,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    with scoped_session_for_company(company_id) as session:
        run = OptimizationRun(
            company_id=company_id,
            request_id=request_id,
            vehicles_requested=body.vehicles,
            vehicle_capacity=body.vehicle_capacity,
            total_distance_km=float(result.total_distance_km),
            total_cost=float(result.total_cost),
            baseline_distance_km=float(result.baseline_distance_km),
            baseline_cost=float(result.baseline_cost),
            cost_reduction_pct=float(result.cost_reduction_pct),
            vehicles_used=int(result.vehicles_used),
        )
        session.add(run)
        session.flush()
        run_id = run.id

        for r in result.routes:
            session.add(RouteRecord(
                run_id=run_id,
                company_id=company_id,
                zone_id=r.zone_id,
                stop_ids=[s.id for s in r.stops],
                distance_km=float(r.total_distance_km),
            ))

    manager.broadcast_sync(job_id, {
        "job_id": job_id,
        "status": "COMPLETED",
        "progress_pct": 100,
        "message": "Optimization completed successfully"
    })
    elapsed_ms = round((time.monotonic() - start) * 1000, 1)

    return {
        "request_id": request_id,
        "company_id": current_company["company_slug"],
        "routes": [
            {"zone_id": r.zone_id, "stop_ids": [s.id for s in r.stops], "distance_km": float(r.total_distance_km)}
            for r in result.routes
        ],
        "summary": {
            "total_distance_km": float(result.total_distance_km),
            "total_cost": float(result.total_cost),
            "vehicles_used": int(result.vehicles_used),
            "baseline_distance_km": float(result.baseline_distance_km),
            "baseline_cost": float(result.baseline_cost),
            "cost_reduction_pct": float(result.cost_reduction_pct),
            "solver_used": result.solver_used,
            "distance_provider_used": result.distance_provider_used,
        },
        "elapsed_ms": elapsed_ms,
    }


@app.get("/runs")
def list_runs(current_company: dict = Depends(get_current_company)):
    company_id = current_company["company_id"]
    with scoped_session_for_company(company_id) as session:
        runs = session.query(OptimizationRun).filter_by(company_id=company_id).all()
        return {
            "company_id": current_company["company_slug"],
            "runs": [
                {
                    "request_id": r.request_id,
                    "total_cost": float(r.total_cost) if r.total_cost is not None else 0.0,
                    "cost_reduction_pct": float(r.cost_reduction_pct) if r.cost_reduction_pct is not None else 0.0,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in runs
            ],
        }


# ---------- New Models for Reoptimization, Sustainability & Simulation ----------

from typing import Any
from routeopt.routing import Route
from routeopt.distance import get_distance_provider
from routeopt.dynamic import (
    reoptimize_insert_order,
    reoptimize_cancel_order,
    reoptimize_vehicle_breakdown,
    reoptimize_traffic_delay,
)
from routeopt.sustainability import evaluate_sustainability, MultiObjectiveWeights
from routeopt.simulation import run_disruption_simulation
from routeopt.db.models import ReoptimizationRecord, SimulationRecord


class RouteIn(BaseModel):
    zone_id: int = 0
    vehicle_id: str | None = None
    vehicle_name: str | None = None
    stop_ids: list[str] = Field(default_factory=list)
    stops: list[StopIn] | None = None
    distance_km: float = 0.0
    total_distance_km: float = 0.0
    duration_min: float = 0.0
    total_duration_minutes: float = 0.0


class InsertOrderRequest(BaseModel):
    job_id: str | None = None
    new_stop: StopIn
    pickup_stop: StopIn | None = None
    active_routes: list[RouteIn]
    vehicle_specs: list[VehicleSpecIn] | None = None
    depot: DepotIn | None = None
    completed_stop_ids: list[str] = Field(default_factory=list)
    average_speed_kmh: float = 30.0


class CancelOrderRequest(BaseModel):
    job_id: str | None = None
    cancelled_stop_id: str
    active_routes: list[RouteIn]
    completed_stop_ids: list[str] = Field(default_factory=list)
    average_speed_kmh: float = 30.0


class VehicleBreakdownRequest(BaseModel):
    job_id: str | None = None
    broken_vehicle_id: str
    active_routes: list[RouteIn]
    vehicle_specs: list[VehicleSpecIn] | None = None
    depot: DepotIn | None = None
    completed_stop_ids: list[str] = Field(default_factory=list)
    average_speed_kmh: float = 30.0


class TrafficDelayRequest(BaseModel):
    job_id: str | None = None
    vehicle_id: str
    delay_minutes: float = Field(..., gt=0)
    active_routes: list[RouteIn]
    average_speed_kmh: float = 30.0


class SimulationRequest(BaseModel):
    job_id: str | None = None
    scenario_type: str = Field(..., description="'vehicle_breakdown', 'emergency_order', 'traffic_surge', or 'dock_delay'")
    scenario_params: dict[str, Any] = Field(default_factory=dict)
    baseline_routes: list[RouteIn]
    vehicle_specs: list[VehicleSpecIn] | None = None
    depot: DepotIn | None = None
    completed_stop_ids: list[str] = Field(default_factory=list)
    average_speed_kmh: float = 30.0


class SustainabilityRequest(BaseModel):
    routes: list[RouteIn]
    fuel_type: str = "diesel"
    fixed_cost_per_vehicle: float = 50.0
    weights: dict[str, float] | None = None


class RegisterJSON(BaseModel):
    name: str
    slug: str
    password: str


class LoginJSON(BaseModel):
    slug: str
    password: str


def _parse_stop_in(s: StopIn) -> Stop:
    return Stop(
        id=s.id,
        lat=s.lat,
        lon=s.lon,
        demand=s.demand,
        time_window=tuple(s.time_window) if s.time_window and len(s.time_window) == 2 else None,
        service_duration=s.service_duration,
        pickup_stop_id=s.pickup_stop_id,
        soft_time_window=tuple(s.soft_time_window) if s.soft_time_window and len(s.soft_time_window) == 2 else None,
        early_penalty_cost=s.early_penalty_cost,
        late_penalty_cost=s.late_penalty_cost,
    )


def _parse_route_in(r: RouteIn, depot: Stop | None = None) -> Route:
    stops: list[Stop] = []
    if r.stops:
        stops = [_parse_stop_in(s) for s in r.stops]
    elif r.stop_ids:
        for sid in r.stop_ids:
            if depot and sid == depot.id:
                stops.append(depot)
            else:
                stops.append(Stop(id=sid, lat=depot.lat if depot else 28.60, lon=depot.lon if depot else 77.20))
    return Route(
        zone_id=r.zone_id,
        stops=stops,
        total_distance_km=float(r.total_distance_km or r.distance_km),
        total_duration_minutes=float(r.total_duration_minutes or r.duration_min),
        vehicle_id=r.vehicle_id or f"v_{r.zone_id}",
        vehicle_name=r.vehicle_name or f"Vehicle {r.zone_id + 1}",
    )


def _serialize_routes(routes: list[Route]) -> list[dict]:
    return [
        {
            "zone_id": r.zone_id,
            "vehicle_id": getattr(r, "vehicle_id", None) or f"v_{r.zone_id}",
            "vehicle_name": getattr(r, "vehicle_name", None) or f"Vehicle {r.zone_id + 1}",
            "stop_ids": [s.id for s in r.stops],
            "distance_km": float(r.total_distance_km),
            "duration_min": float(r.total_duration_minutes),
        }
        for r in routes
    ]


# ---------- Frontend Auth Endpoints ----------

@app.post("/api/v1/auth/register", status_code=201)
@limiter.limit("30/minute")
def register_v1(request: Request, body: RegisterJSON):
    with admin_session() as session:
        existing = session.query(Company).filter_by(slug=body.slug).first()
        if existing:
            raise HTTPException(status_code=409, detail="Company slug already registered")

        company = Company(
            slug=body.slug,
            name=body.name,
            hashed_password=hash_password(body.password),
        )
        session.add(company)
        session.flush()
        cid = str(company.id)
        cname = company.name
        cslug = company.slug
        token = create_access_token(cid, cslug)

    return {
        "id": cid,
        "name": cname,
        "slug": cslug,
        "token": token,
    }


@app.post("/api/v1/auth/login")
@limiter.limit("60/minute")
def login_v1(request: Request, body: LoginJSON):
    with admin_session() as session:
        company = session.query(Company).filter_by(slug=body.slug).first()
        if not company or not company.hashed_password or not verify_password(
            body.password, company.hashed_password
        ):
            raise HTTPException(status_code=401, detail="Incorrect company slug or password")

        cid = str(company.id)
        cname = company.name
        cslug = company.slug
        token = create_access_token(cid, cslug)

    return {
        "id": cid,
        "name": cname,
        "slug": cslug,
        "token": token,
    }


# ---------- Vehicle Delete ----------

@app.delete("/vehicles/{vehicle_id}")
@app.delete("/api/v1/vehicles/{vehicle_id}")
def delete_vehicle(
    vehicle_id: str,
    current_company: dict = Depends(get_current_company),
):
    company_id = current_company["company_id"]
    with scoped_session_for_company(company_id) as session:
        vehicle = session.query(Vehicle).filter_by(id=vehicle_id, company_id=company_id).first()
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        vehicle.is_active = False

    return {"status": "success", "message": f"Vehicle {vehicle_id} deactivated"}


# ---------- Forwarding Aliases for Frontend API ----------

@app.post("/api/v1/optimize")
def optimize_v1(
    request: Request,
    body: OptimizeRequest,
    current_company: dict = Depends(get_current_company),
):
    return optimize(request=request, body=body, current_company=current_company)


@app.get("/api/v1/vehicles")
def list_vehicles_v1(current_company: dict = Depends(get_current_company)):
    return list_vehicles(current_company=current_company)


@app.post("/api/v1/vehicles", status_code=201)
def create_vehicle_v1(
    body: VehicleCreate,
    current_company: dict = Depends(get_current_company),
):
    return create_vehicle(body=body, current_company=current_company)


@app.get("/api/v1/runs")
def list_runs_v1(current_company: dict = Depends(get_current_company)):
    return list_runs(current_company=current_company)


# ---------- Dynamic Route Reoptimization Endpoints ----------

@app.post("/reoptimize/insert-order")
@app.post("/api/v1/reoptimize/insert-order")
def api_reoptimize_insert_order(
    body: InsertOrderRequest,
    current_company: dict = Depends(get_current_company),
):
    depot_stop = Stop(id="depot", lat=body.depot.lat, lon=body.depot.lon) if body.depot else None
    active_routes = [_parse_route_in(r, depot_stop) for r in body.active_routes]
    new_stop = _parse_stop_in(body.new_stop)
    pickup_stop = _parse_stop_in(body.pickup_stop) if body.pickup_stop else None

    specs = (
        [
            VehicleSpec(
                id=vs.id,
                name=vs.name,
                capacity=vs.capacity,
                cost_per_km=vs.cost_per_km,
                fixed_cost=vs.fixed_cost,
                max_distance_km=vs.max_distance_km,
            )
            for vs in body.vehicle_specs
        ]
        if body.vehicle_specs
        else [VehicleSpec(id=getattr(r, "vehicle_id", f"v_{r.zone_id}"), capacity=20.0) for r in active_routes]
    )

    result = reoptimize_insert_order(
        active_routes=active_routes,
        new_stop=new_stop,
        vehicle_specs=specs,
        depot=depot_stop,
        completed_stop_ids=set(body.completed_stop_ids),
        pickup_stop=pickup_stop,
        average_speed_kmh=body.average_speed_kmh,
    )

    company_id = current_company["company_id"]
    with scoped_session_for_company(company_id) as session:
        rec = ReoptimizationRecord(
            company_id=company_id,
            event_type="INSERT_ORDER",
            affected_vehicles=result.affected_vehicle_ids,
            details={
                "new_stop_id": new_stop.id,
                "success": result.success,
                "distance_delta_km": result.distance_delta_km,
                "duration_delta_minutes": result.duration_delta_minutes,
            },
        )
        session.add(rec)

    if body.job_id:
        manager.broadcast_sync(body.job_id, {
            "job_id": body.job_id,
            "status": "REOPTIMIZED",
            "event": "INSERT_ORDER",
            "affected_vehicles": result.affected_vehicle_ids,
            "message": f"Order {new_stop.id} dynamically inserted into fleet route",
        })

    return {
        "success": result.success,
        "event_type": result.event_type,
        "affected_vehicle_ids": result.affected_vehicle_ids,
        "routes": _serialize_routes(result.routes),
        "unassigned_stops": [{"stop_id": u.stop_id, "demand": u.demand, "reason": u.reason} for u in result.unassigned_stops],
        "total_distance_km": result.total_distance_km,
        "distance_delta_km": result.distance_delta_km,
        "total_duration_minutes": result.total_duration_minutes,
        "duration_delta_minutes": result.duration_delta_minutes,
        "execution_time_seconds": result.execution_time_seconds,
        "timestamp": result.timestamp,
    }


@app.post("/reoptimize/cancel-order")
@app.post("/api/v1/reoptimize/cancel-order")
def api_reoptimize_cancel_order(
    body: CancelOrderRequest,
    current_company: dict = Depends(get_current_company),
):
    active_routes = [_parse_route_in(r) for r in body.active_routes]

    try:
        result = reoptimize_cancel_order(
            active_routes=active_routes,
            cancelled_stop_id=body.cancelled_stop_id,
            completed_stop_ids=set(body.completed_stop_ids),
            average_speed_kmh=body.average_speed_kmh,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    company_id = current_company["company_id"]
    with scoped_session_for_company(company_id) as session:
        rec = ReoptimizationRecord(
            company_id=company_id,
            event_type="CANCEL_ORDER",
            affected_vehicles=result.affected_vehicle_ids,
            details={
                "cancelled_stop_id": body.cancelled_stop_id,
                "success": result.success,
                "distance_delta_km": result.distance_delta_km,
            },
        )
        session.add(rec)

    if body.job_id:
        manager.broadcast_sync(body.job_id, {
            "job_id": body.job_id,
            "status": "REOPTIMIZED",
            "event": "CANCEL_ORDER",
            "affected_vehicles": result.affected_vehicle_ids,
            "message": f"Order {body.cancelled_stop_id} cancelled; route resequenced",
        })

    return {
        "success": result.success,
        "event_type": result.event_type,
        "affected_vehicle_ids": result.affected_vehicle_ids,
        "routes": _serialize_routes(result.routes),
        "total_distance_km": result.total_distance_km,
        "distance_delta_km": result.distance_delta_km,
        "total_duration_minutes": result.total_duration_minutes,
        "duration_delta_minutes": result.duration_delta_minutes,
        "execution_time_seconds": result.execution_time_seconds,
        "timestamp": result.timestamp,
    }


@app.post("/reoptimize/vehicle-breakdown")
@app.post("/api/v1/reoptimize/vehicle-breakdown")
def api_reoptimize_breakdown(
    body: VehicleBreakdownRequest,
    current_company: dict = Depends(get_current_company),
):
    depot_stop = Stop(id="depot", lat=body.depot.lat, lon=body.depot.lon) if body.depot else None
    active_routes = [_parse_route_in(r, depot_stop) for r in body.active_routes]

    specs = (
        [
            VehicleSpec(
                id=vs.id,
                name=vs.name,
                capacity=vs.capacity,
                cost_per_km=vs.cost_per_km,
                fixed_cost=vs.fixed_cost,
                max_distance_km=vs.max_distance_km,
            )
            for vs in body.vehicle_specs
        ]
        if body.vehicle_specs
        else [VehicleSpec(id=getattr(r, "vehicle_id", f"v_{r.zone_id}"), capacity=20.0) for r in active_routes]
    )

    try:
        result = reoptimize_vehicle_breakdown(
            active_routes=active_routes,
            broken_vehicle_id=body.broken_vehicle_id,
            vehicle_specs=specs,
            depot=depot_stop,
            completed_stop_ids=set(body.completed_stop_ids),
            average_speed_kmh=body.average_speed_kmh,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    company_id = current_company["company_id"]
    with scoped_session_for_company(company_id) as session:
        rec = ReoptimizationRecord(
            company_id=company_id,
            event_type="VEHICLE_BREAKDOWN",
            affected_vehicles=result.affected_vehicle_ids,
            details={
                "broken_vehicle_id": body.broken_vehicle_id,
                "unassigned_count": len(result.unassigned_stops),
            },
        )
        session.add(rec)

    if body.job_id:
        manager.broadcast_sync(body.job_id, {
            "job_id": body.job_id,
            "status": "REOPTIMIZED",
            "event": "VEHICLE_BREAKDOWN",
            "affected_vehicles": result.affected_vehicle_ids,
            "message": f"Breakdown on vehicle {body.broken_vehicle_id}; stops reallocated to surviving fleet",
        })

    return {
        "success": result.success,
        "event_type": result.event_type,
        "affected_vehicle_ids": result.affected_vehicle_ids,
        "routes": _serialize_routes(result.routes),
        "unassigned_stops": [{"stop_id": u.stop_id, "demand": u.demand, "reason": u.reason} for u in result.unassigned_stops],
        "total_distance_km": result.total_distance_km,
        "distance_delta_km": result.distance_delta_km,
        "total_duration_minutes": result.total_duration_minutes,
        "duration_delta_minutes": result.duration_delta_minutes,
        "execution_time_seconds": result.execution_time_seconds,
        "timestamp": result.timestamp,
    }


@app.post("/reoptimize/traffic-delay")
@app.post("/api/v1/reoptimize/traffic-delay")
def api_reoptimize_traffic_delay(
    body: TrafficDelayRequest,
    current_company: dict = Depends(get_current_company),
):
    active_routes = [_parse_route_in(r) for r in body.active_routes]

    result = reoptimize_traffic_delay(
        active_routes=active_routes,
        vehicle_id=body.vehicle_id,
        delay_minutes=body.delay_minutes,
        average_speed_kmh=body.average_speed_kmh,
    )

    return {
        "success": result.success,
        "event_type": result.event_type,
        "affected_vehicle_ids": result.affected_vehicle_ids,
        "routes": _serialize_routes(result.routes),
        "total_distance_km": result.total_distance_km,
        "distance_delta_km": result.distance_delta_km,
        "total_duration_minutes": result.total_duration_minutes,
        "duration_delta_minutes": result.duration_delta_minutes,
        "execution_time_seconds": result.execution_time_seconds,
        "timestamp": result.timestamp,
    }


# ---------- Digital Twin Disruption Simulation Endpoint ----------

@app.post("/simulate")
@app.post("/api/v1/simulate")
def api_simulate_disruption(
    body: SimulationRequest,
    current_company: dict = Depends(get_current_company),
):
    depot_stop = Stop(id="depot", lat=body.depot.lat, lon=body.depot.lon) if body.depot else None
    baseline_routes = [_parse_route_in(r, depot_stop) for r in body.baseline_routes]

    specs = (
        [
            VehicleSpec(
                id=vs.id,
                name=vs.name,
                capacity=vs.capacity,
                cost_per_km=vs.cost_per_km,
                fixed_cost=vs.fixed_cost,
                max_distance_km=vs.max_distance_km,
            )
            for vs in body.vehicle_specs
        ]
        if body.vehicle_specs
        else [VehicleSpec(id=getattr(r, "vehicle_id", f"v_{r.zone_id}"), capacity=20.0) for r in baseline_routes]
    )

    try:
        report = run_disruption_simulation(
            baseline_routes=baseline_routes,
            scenario_type=body.scenario_type,
            params=body.scenario_params,
            vehicle_specs=specs,
            depot=depot_stop,
            completed_stop_ids=set(body.completed_stop_ids),
            average_speed_kmh=body.average_speed_kmh,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    company_id = current_company["company_id"]
    with scoped_session_for_company(company_id) as session:
        rec = SimulationRecord(
            company_id=company_id,
            scenario_type=report.scenario_type,
            scenario_name=report.scenario_name,
            report={
                "description": report.description,
                "distance_delta_km": report.distance_km.absolute_delta,
                "duration_delta_minutes": report.duration_minutes.absolute_delta,
                "cost_delta_usd": report.operating_cost_usd.absolute_delta,
                "unserved_orders": report.unserved_orders_count,
            },
        )
        session.add(rec)

    if body.job_id:
        manager.broadcast_sync(body.job_id, {
            "job_id": body.job_id,
            "status": "SIMULATION_COMPLETED",
            "scenario": report.scenario_name,
            "message": f"Simulation finished: cost delta ${report.operating_cost_usd.absolute_delta}",
        })

    return {
        "scenario_name": report.scenario_name,
        "scenario_type": report.scenario_type,
        "description": report.description,
        "distance_km": {
            "baseline": report.distance_km.baseline_value,
            "simulated": report.distance_km.simulated_value,
            "delta": report.distance_km.absolute_delta,
            "pct": report.distance_km.percentage_delta,
        },
        "duration_minutes": {
            "baseline": report.duration_minutes.baseline_value,
            "simulated": report.duration_minutes.simulated_value,
            "delta": report.duration_minutes.absolute_delta,
            "pct": report.duration_minutes.percentage_delta,
        },
        "operating_cost_usd": {
            "baseline": report.operating_cost_usd.baseline_value,
            "simulated": report.operating_cost_usd.simulated_value,
            "delta": report.operating_cost_usd.absolute_delta,
            "pct": report.operating_cost_usd.percentage_delta,
        },
        "co2_emissions_kg": {
            "baseline": report.co2_emissions_kg.baseline_value,
            "simulated": report.co2_emissions_kg.simulated_value,
            "delta": report.co2_emissions_kg.absolute_delta,
            "pct": report.co2_emissions_kg.percentage_delta,
        },
        "vehicles_used": {
            "baseline": int(report.vehicles_used.baseline_value),
            "simulated": int(report.vehicles_used.simulated_value),
            "delta": int(report.vehicles_used.absolute_delta),
        },
        "sla_violations_count": report.sla_violations_count,
        "unserved_orders_count": report.unserved_orders_count,
        "execution_time_seconds": report.execution_time_seconds,
        "baseline_routes": report.baseline_routes,
        "simulated_routes": report.simulated_routes,
        "unserved_orders": report.unserved_orders,
        "timestamp": report.timestamp,
    }


# ---------- Sustainability Assessment Endpoint ----------

@app.post("/sustainability")
@app.post("/api/v1/sustainability")
def api_sustainability_assessment(
    body: SustainabilityRequest,
    current_company: dict = Depends(get_current_company),
):
    routes = [_parse_route_in(r) for r in body.routes]
    weights = MultiObjectiveWeights(**body.weights) if body.weights else None

    assessment = evaluate_sustainability(
        routes=routes,
        fuel_type=body.fuel_type,
        weights=weights,
        fixed_cost_per_vehicle=body.fixed_cost_per_vehicle,
    )

    return {
        "total_distance_km": assessment.total_distance_km,
        "total_duration_minutes": assessment.total_duration_minutes,
        "vehicles_active": assessment.vehicles_active,
        "fuel_consumption_liters": assessment.fuel_consumption_liters,
        "electricity_consumption_kwh": assessment.electricity_consumption_kwh,
        "total_co2_emissions_kg": assessment.total_co2_emissions_kg,
        "carbon_offset_cost_usd": assessment.carbon_offset_cost_usd,
        "total_fuel_cost_usd": assessment.total_fuel_cost_usd,
        "total_labor_cost_usd": assessment.total_labor_cost_usd,
        "total_maintenance_cost_usd": assessment.total_maintenance_cost_usd,
        "total_fixed_dispatch_cost_usd": assessment.total_fixed_dispatch_cost_usd,
        "total_operating_cost_usd": assessment.total_operating_cost_usd,
        "composite_sustainability_score": assessment.composite_sustainability_score,
        "per_route_metrics": [
            {
                "vehicle_id": m.vehicle_id,
                "fuel_type": m.fuel_type,
                "distance_km": m.distance_km,
                "duration_minutes": m.duration_minutes,
                "energy_consumed": m.energy_consumed,
                "energy_unit": m.energy_unit,
                "co2_emissions_kg": m.co2_emissions_kg,
                "total_route_cost": m.total_route_cost,
            }
            for m in assessment.per_route_metrics
        ],
        "weights_used": assessment.weights_used,
    }


# ---------- Fleet Telemetry Simulation WebSocket ----------

@app.websocket("/ws/fleet/{job_id}")
async def websocket_fleet_telemetry(websocket: WebSocket, job_id: str):
    await websocket.accept()
    try:
        await websocket.send_json({
            "job_id": job_id,
            "status": "CONNECTED",
            "simulation_mode": True,
            "message": "Connected to RouteOpt live vehicle telemetry simulator",
        })
        while True:
            # Client can ping or send simulation parameters
            data = await websocket.receive_text()
            await websocket.send_json({
                "job_id": job_id,
                "simulation_mode": True,
                "status": "TELEMETRY_FRAME",
                "ack": True,
            })
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
