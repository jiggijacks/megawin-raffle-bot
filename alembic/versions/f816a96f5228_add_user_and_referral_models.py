"""Add User and referral models

Revision ID: f816a96f5228
Revises: a8e4f71cbed8
Create Date: 2025-10-19 23:26:18.863902

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f816a96f5228'
down_revision: Union[str, Sequence[str], None] = 'a8e4f71cbed8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
