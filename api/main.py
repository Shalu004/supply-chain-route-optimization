"""
FastAPI application for RouteOpt API service.
"""

import logging
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError
from pydantic import BaseModel, Field
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

    stops = [Stop(id=s.id, lat=s.lat, lon=s.lon, demand=s.demand) for s in body.stops]
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
