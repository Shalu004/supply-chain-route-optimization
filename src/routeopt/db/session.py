"""
Database session management with per-request tenant scoping.
"""

import os
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:devpassword@localhost:5432/routeopt",
)

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(bind=engine)


@contextmanager
def scoped_session_for_company(company_id: str):
    """
    Open a database session scoped to one company.

    Switches role to non-superuser `routeopt_app` so PostgreSQL RLS
    is strictly enforced, using app.current_company_id to determine row visibility.
    """

    session = SessionLocal()

    try:
        session.execute(text("SET LOCAL ROLE routeopt_app"))
        session.execute(
            text("SET LOCAL app.current_company_id = :cid"),
            {"cid": company_id},
        )

        yield session
        session.commit()

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


@contextmanager
def admin_session():
    """
    Unscoped session for administrative operations.
    Use sparingly.
    """

    session = SessionLocal()

    try:
        yield session
        session.commit()

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()
