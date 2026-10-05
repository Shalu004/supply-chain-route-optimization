"""enable row level security

Revision ID: f420930c27fb
Revises: cbcebad8122b
Create Date: 2026-09-08 12:54:45.554705

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f420930c27fb'
down_revision: Union[str, Sequence[str], None] = 'cbcebad8122b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    tables = ["stops", "optimization_runs", "routes"]
    for table in tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table};")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_policy ON {table}
            USING (company_id::text = NULLIF(current_setting('app.current_company_id', true), ''))
            WITH CHECK (company_id::text = NULLIF(current_setting('app.current_company_id', true), ''));
            """
        )


def downgrade() -> None:
    """Downgrade schema."""
    tables = ["stops", "optimization_runs", "routes"]
    for table in tables:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
