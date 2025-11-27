"""Add User model and update raffle_entries table

Revision ID: f87974e1c8f4
Revises: c6853a3f1beb
Create Date: 2025-10-19 23:30:13.411391

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f87974e1c8f4'
down_revision: Union[str, Sequence[str], None] = 'c6853a3f1beb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
