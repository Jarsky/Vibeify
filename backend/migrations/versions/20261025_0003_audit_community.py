"""audit log, billing events, community sharing

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25 10:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor_id', sa.String(length=32), nullable=True),
    sa.Column('actor_label', sa.String(length=320), nullable=False),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('target_type', sa.String(length=30), nullable=True),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('target_label', sa.String(length=320), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_log_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_actor_id'), ['actor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_target_id'), ['target_id'], unique=False)

    op.create_table('billing_events',
    sa.Column('id', sa.String(length=255), nullable=False),
    sa.Column('type', sa.String(length=80), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=True),
    sa.Column('customer_id', sa.String(length=64), nullable=True),
    sa.Column('summary', sa.String(length=500), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('stripe_created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_billing_events'))
    )
    with op.batch_alter_table('billing_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_billing_events_type'), ['type'], unique=False)
        batch_op.create_index(batch_op.f('ix_billing_events_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_billing_events_received_at'), ['received_at'], unique=False)

    with op.batch_alter_table('generations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('spotify_public', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('shared', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('community_hidden', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('generations', schema=None) as batch_op:
        batch_op.drop_column('community_hidden')
        batch_op.drop_column('shared')
        batch_op.drop_column('spotify_public')
    op.drop_table('billing_events')
    op.drop_table('audit_log')
