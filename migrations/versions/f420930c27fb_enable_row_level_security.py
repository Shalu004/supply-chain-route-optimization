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
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
