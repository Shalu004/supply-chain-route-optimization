"""
Integration tests for PostgreSQL database layer, SQLAlchemy models, and multitenancy (including RLS).
"""

import sys
import unittest
import uuid
from pathlib import Path
from sqlalchemy.exc import DBAPIError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routeopt.clustering import Stop as ClusterStop
from routeopt.db.models import Company, Stop, OptimizationRun, RouteRecord, Vehicle
from routeopt.db.session import admin_session, scoped_session_for_company
from routeopt.pipeline import run_optimization


class TestDatabaseIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Clean test data before running tests."""
        with admin_session() as session:
            session.query(RouteRecord).delete()
            session.query(OptimizationRun).delete()
            session.query(Stop).delete()
            session.query(Vehicle).delete()
            session.query(Company).delete()

    def test_company_creation(self):
        """Test creating a company tenant in PostgreSQL."""
        company_slug = f"acme-{uuid.uuid4().hex[:6]}"
        with admin_session() as session:
            company = Company(name="Acme Logistics", slug=company_slug)
            session.add(company)
            session.flush()
            company_id = company.id

        # Verify company persists
        with admin_session() as session:
            retrieved = session.query(Company).filter_by(id=company_id).first()
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.name, "Acme Logistics")

    def test_multitenancy_isolation(self):
        """Test that data created for Company A is isolated from Company B."""
        slug_a = f"tenant-a-{uuid.uuid4().hex[:6]}"
        slug_b = f"tenant-b-{uuid.uuid4().hex[:6]}"

        with admin_session() as session:
            comp_a = Company(name="Tenant A", slug=slug_a)
            comp_b = Company(name="Tenant B", slug=slug_b)
            session.add_all([comp_a, comp_b])
            session.flush()
            id_a, id_b = comp_a.id, comp_b.id

        # Add stops for Tenant A
        with scoped_session_for_company(str(id_a)) as session:
            stop_a1 = Stop(company_id=id_a, external_id="A1", lat=28.61, lon=77.21, demand=2.0)
            stop_a2 = Stop(company_id=id_a, external_id="A2", lat=28.62, lon=77.22, demand=3.0)
            session.add_all([stop_a1, stop_a2])

        # Add stops for Tenant B
        with scoped_session_for_company(str(id_b)) as session:
            stop_b1 = Stop(company_id=id_b, external_id="B1", lat=19.07, lon=72.87, demand=5.0)
            session.add(stop_b1)

        # Verify Tenant A stops
        with admin_session() as session:
            stops_a = session.query(Stop).filter_by(company_id=id_a).all()
            stops_b = session.query(Stop).filter_by(company_id=id_b).all()
            self.assertEqual(len(stops_a), 2)
            self.assertEqual(len(stops_b), 1)
            self.assertEqual({s.external_id for s in stops_a}, {"A1", "A2"})
            self.assertEqual({s.external_id for s in stops_b}, {"B1"})

    def test_rls_query_isolation(self):
        """Test that PostgreSQL RLS restricts unscoped SELECT queries to the active tenant session."""
        slug_a = f"rls-a-{uuid.uuid4().hex[:6]}"
        slug_b = f"rls-b-{uuid.uuid4().hex[:6]}"

        with admin_session() as session:
            comp_a = Company(name="RLS Comp A", slug=slug_a)
            comp_b = Company(name="RLS Comp B", slug=slug_b)
            session.add_all([comp_a, comp_b])
            session.flush()
            id_a, id_b = comp_a.id, comp_b.id

        # Add stops under Tenant A scoped session
        with scoped_session_for_company(str(id_a)) as session:
            stop_a = Stop(company_id=id_a, external_id="RLS_A", lat=28.5, lon=77.1, demand=1.0)
            session.add(stop_a)

        # Query stops under Tenant B scoped session without explicit company_id filter
        with scoped_session_for_company(str(id_b)) as session:
            # Unscoped query - RLS should filter out Tenant A's stops at the database level
            all_stops_b = session.query(Stop).all()
            # If RLS is enforced, Comp B sees 0 stops despite Comp A having 1 stop in DB
            self.assertEqual(len(all_stops_b), 0)

    def test_rls_insert_prevention(self):
        """Test that PostgreSQL RLS WITH CHECK policy prevents inserting rows for another tenant."""
        slug_a = f"rls-ins-a-{uuid.uuid4().hex[:6]}"
        slug_b = f"rls-ins-b-{uuid.uuid4().hex[:6]}"

        with admin_session() as session:
            comp_a = Company(name="RLS Ins A", slug=slug_a)
            comp_b = Company(name="RLS Ins B", slug=slug_b)
            session.add_all([comp_a, comp_b])
            session.flush()
            id_a, id_b = comp_a.id, comp_b.id

        # Attempt to insert a stop for Tenant A while session is scoped to Tenant B
        with self.assertRaises(DBAPIError):
            with scoped_session_for_company(str(id_b)) as session:
                illegal_stop = Stop(company_id=id_a, external_id="ILLEGAL", lat=28.5, lon=77.1, demand=1.0)
                session.add(illegal_stop)
                session.flush()

    def test_pipeline_db_persistence(self):
        """Test running optimization engine and storing results in database."""
        slug = f"express-{uuid.uuid4().hex[:6]}"
        with admin_session() as session:
            company = Company(name="Express Delivery", slug=slug)
            session.add(company)
            session.flush()
            company_id = company.id

        # Prepare synthetic input stops
        input_stops = [
            ClusterStop(id=f"stop_{i}", lat=28.60 + i * 0.01, lon=77.20 + i * 0.01, demand=1.0)
            for i in range(10)
        ]

        # Run optimization engine
        result = run_optimization(stops=input_stops, n_vehicles=2, vehicle_capacity=10.0)

        # Save run and routes into PostgreSQL
        request_id = str(uuid.uuid4())[:8]
        with scoped_session_for_company(str(company_id)) as session:
            run_rec = OptimizationRun(
                company_id=company_id,
                request_id=request_id,
                vehicles_requested=2,
                vehicle_capacity=10.0,
                total_distance_km=float(result.total_distance_km),
                total_cost=float(result.total_cost),
                baseline_distance_km=float(result.baseline_distance_km),
                baseline_cost=float(result.baseline_cost),
                cost_reduction_pct=float(result.cost_reduction_pct),
                vehicles_used=int(result.vehicles_used),
            )
            session.add(run_rec)
            session.flush()

            for route in result.routes:
                route_rec = RouteRecord(
                    run_id=run_rec.id,
                    company_id=company_id,
                    zone_id=route.zone_id,
                    stop_ids=[s.id for s in route.stops],
                    distance_km=float(route.total_distance_km),
                )
                session.add(route_rec)

        # Verify optimization run and route records in DB
        with admin_session() as session:
            saved_run = session.query(OptimizationRun).filter_by(request_id=request_id).first()
            self.assertIsNotNone(saved_run)
            self.assertEqual(saved_run.company_id, company_id)
            self.assertAlmostEqual(saved_run.total_cost, result.total_cost, places=4)

            saved_routes = session.query(RouteRecord).filter_by(run_id=saved_run.id).all()
            self.assertEqual(len(saved_routes), len(result.routes))


if __name__ == "__main__":
    unittest.main()
