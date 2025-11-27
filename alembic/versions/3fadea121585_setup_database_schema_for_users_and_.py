"""Setup database schema for users and raffle entries

Revision ID: 3fadea121585
Revises: dcd0ee463830
Create Date: 2025-10-19 23:31:00.442496

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3fadea121585'
down_revision: Union[str, Sequence[str], None] = 'dcd0ee463830'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
