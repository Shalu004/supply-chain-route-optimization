"""add reoptimization and simulation tables with RLS

Revision ID: 9a12bc34de56
Revises: 8901abcdef23
Create Date: 2026-10-18 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '9a12bc34de56'
down_revision: Union[str, Sequence[str], None] = '8901abcdef23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create reoptimization_events table
    op.create_table(
        'reoptimization_events',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('company_id', UUID(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('affected_vehicles', sa.JSON(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reoptimization_events_company_id'), 'reoptimization_events', ['company_id'], unique=False)

    # Enable and Force RLS on reoptimization_events
    op.execute("ALTER TABLE reoptimization_events ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE reoptimization_events FORCE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON reoptimization_events;")
    op.execute(
        """
        CREATE POLICY tenant_isolation_policy ON reoptimization_events
        USING (company_id::text = NULLIF(current_setting('app.current_company_id', true), ''))
        WITH CHECK (company_id::text = NULLIF(current_setting('app.current_company_id', true), ''));
        """
    )

    # 2. Create simulation_runs table
    op.create_table(
        'simulation_runs',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('company_id', UUID(as_uuid=True), nullable=False),
        sa.Column('scenario_type', sa.String(), nullable=False),
        sa.Column('scenario_name', sa.String(), nullable=False),
        sa.Column('report', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_simulation_runs_company_id'), 'simulation_runs', ['company_id'], unique=False)

    # Enable and Force RLS on simulation_runs
    op.execute("ALTER TABLE simulation_runs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE simulation_runs FORCE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON simulation_runs;")
    op.execute(
        """
        CREATE POLICY tenant_isolation_policy ON simulation_runs
        USING (company_id::text = NULLIF(current_setting('app.current_company_id', true), ''))
        WITH CHECK (company_id::text = NULLIF(current_setting('app.current_company_id', true), ''));
        """
    )


def downgrade() -> None:
    # Drop simulation_runs
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON simulation_runs;")
    op.execute("ALTER TABLE simulation_runs NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE simulation_runs DISABLE ROW LEVEL SECURITY;")
    op.drop_index(op.f('ix_simulation_runs_company_id'), table_name='simulation_runs')
    op.drop_table('simulation_runs')

    # Drop reoptimization_events
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON reoptimization_events;")
    op.execute("ALTER TABLE reoptimization_events NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE reoptimization_events DISABLE ROW LEVEL SECURITY;")
    op.drop_index(op.f('ix_reoptimization_events_company_id'), table_name='reoptimization_events')
    op.drop_table('reoptimization_events')
