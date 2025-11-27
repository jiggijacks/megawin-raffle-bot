from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_referral_count'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('users', sa.Column('referral_count', sa.Integer(), nullable=True, server_default='0'))

def downgrade() -> None:
    op.drop_column('users', 'referral_count')
