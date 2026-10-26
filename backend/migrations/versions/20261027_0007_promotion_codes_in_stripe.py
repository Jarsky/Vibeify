"""promotion codes live in Stripe

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-27 09:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('promotions') as batch_op:
        batch_op.add_column(sa.Column('stripe_promotion_code_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('stripe_code_active', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('promotions') as batch_op:
        batch_op.drop_column('stripe_code_active')
        batch_op.drop_column('stripe_promotion_code_id')
