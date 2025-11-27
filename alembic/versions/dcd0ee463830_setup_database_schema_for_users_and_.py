"""Setup database schema for users and raffle entries

Revision ID: dcd0ee463830
Revises: f87974e1c8f4
Create Date: 2025-10-19 23:30:37.394809

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dcd0ee463830'
down_revision: Union[str, Sequence[str], None] = 'f87974e1c8f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
