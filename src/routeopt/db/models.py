"""
SQLAlchemy models for RouteOpt's persistent storage.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    DateTime,
    ForeignKey,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class Company(Base):
    __tablename__ = "companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    stops = relationship("Stop", back_populates="company")


class Stop(Base):
    __tablename__ = "stops"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )
    external_id = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    demand = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="stops")


class OptimizationRun(Base):
    __tablename__ = "optimization_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )
    request_id = Column(String, nullable=False)
    vehicles_requested = Column(Integer, nullable=False)
    vehicle_capacity = Column(Float, nullable=False)
    total_distance_km = Column(Float)
    total_cost = Column(Float)
    baseline_distance_km = Column(Float)
    baseline_cost = Column(Float)
    cost_reduction_pct = Column(Float)
    vehicles_used = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company")
    routes = relationship("RouteRecord", back_populates="run")


class RouteRecord(Base):
    __tablename__ = "routes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("optimization_runs.id"),
        nullable=False,
        index=True,
    )
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )
    zone_id = Column(Integer, nullable=False)
    stop_ids = Column(JSON, nullable=False)
    distance_km = Column(Float, nullable=False)

    run = relationship("OptimizationRun", back_populates="routes")