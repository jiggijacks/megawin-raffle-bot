"""Setup database schema for users and raffle entries

Revision ID: a8e4f71cbed8
Revises: 85edef870a40
Create Date: 2025-10-19 23:25:50.957108

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8e4f71cbed8'
down_revision: Union[str, Sequence[str], None] = '85edef870a40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
