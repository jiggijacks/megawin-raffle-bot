"""add affiliate_code, commission_balance, referred_by to users

Revision ID: add_affiliate_fields
Revises: <previous_revision_id_here>
Create Date: 2025-11-13 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_affiliate_fields"
down_revision = "<previous_revision_id_here>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOTE: SQLite supports ADD COLUMN; these columns are nullable so safe to add.
    op.add_column(
        "users",
        sa.Column("affiliate_code", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("commission_balance", sa.Integer(), nullable=True, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("referred_by", sa.Integer(), nullable=True),
    )
    # If you want a DB-level default for commission_balance to be 0, server_default used above.


def downgrade() -> None:
    op.drop_column("users", "referred_by")
    op.drop_column("users", "commission_balance")
    op.drop_column("users", "affiliate_code")
