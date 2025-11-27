"""Add User model and referral support

Revision ID: c6853a3f1beb
Revises: f816a96f5228
Create Date: 2025-10-19 23:27:09.600142

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6853a3f1beb'
down_revision: Union[str, Sequence[str], None] = 'f816a96f5228'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
