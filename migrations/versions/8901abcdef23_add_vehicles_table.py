"""add vehicles table and RLS policy

Revision ID: 8901abcdef23
Revises: 7852c245f7fd
Create Date: 2026-10-05 22:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '8901abcdef23'
down_revision: Union[str, Sequence[str], None] = '7852c245f7fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'vehicles',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('company_id', UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('vehicle_type', sa.String(), nullable=True, server_default='van'),
        sa.Column('capacity', sa.Float(), nullable=False, server_default='20.0'),
        sa.Column('cost_per_km', sa.Float(), nullable=True, server_default='0.9'),
        sa.Column('fixed_cost', sa.Float(), nullable=True, server_default='50.0'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vehicles_company_id'), 'vehicles', ['company_id'], unique=False)

    # Enable and Force Row-Level Security on vehicles table
    op.execute("ALTER TABLE vehicles ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE vehicles FORCE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON vehicles;")
    op.execute(
        """
        CREATE POLICY tenant_isolation_policy ON vehicles
        USING (company_id::text = NULLIF(current_setting('app.current_company_id', true), ''))
        WITH CHECK (company_id::text = NULLIF(current_setting('app.current_company_id', true), ''));
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON vehicles;")
    op.execute("ALTER TABLE vehicles NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE vehicles DISABLE ROW LEVEL SECURITY;")
    op.drop_index(op.f('ix_vehicles_company_id'), table_name='vehicles')
    op.drop_table('vehicles')
