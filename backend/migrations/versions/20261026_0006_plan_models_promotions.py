"""plan default model and model choice, promotions

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-26 12:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('plans') as batch_op:
        batch_op.add_column(sa.Column('default_model_id', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('allow_model_choice', sa.Boolean(), nullable=True))
    op.create_table('promotions',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('code', sa.String(length=40), nullable=True),
    sa.Column('plan_ids', sa.JSON(), nullable=True),
    sa.Column('trial_days', sa.Integer(), nullable=True),
    sa.Column('percent_off', sa.Integer(), nullable=True),
    sa.Column('duration', sa.String(length=10), nullable=False),
    sa.Column('duration_months', sa.Integer(), nullable=True),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('max_redemptions', sa.Integer(), nullable=True),
    sa.Column('redemptions', sa.Integer(), nullable=False),
    sa.Column('reserved', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('first_subscription_only', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('stripe_coupon_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_promotions')),
    sa.UniqueConstraint('code', name=op.f('uq_promotions_code'))
    )


def downgrade() -> None:
    op.drop_table('promotions')
    with op.batch_alter_table('plans') as batch_op:
        batch_op.drop_column('allow_model_choice')
        batch_op.drop_column('default_model_id')
