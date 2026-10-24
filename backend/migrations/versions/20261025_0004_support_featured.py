"""support tickets, featured playlists

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25 12:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('support_tickets',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.String(length=32), nullable=True),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('subject', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('messages', sa.JSON(), nullable=False),
    sa.Column('context', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_support_tickets')),
    sa.UniqueConstraint('number', name=op.f('uq_support_tickets_number'))
    )
    with op.batch_alter_table('support_tickets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_support_tickets_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_support_tickets_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_support_tickets_created_at'), ['created_at'], unique=False)

    with op.batch_alter_table('generations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('featured', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('generations', schema=None) as batch_op:
        batch_op.drop_column('featured')
    op.drop_table('support_tickets')
