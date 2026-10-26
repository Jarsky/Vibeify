"""identity email, email token owner

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26 09:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('identities') as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=320), nullable=True))
    # Email identities: the subject is the address
    op.execute("UPDATE identities SET email = subject WHERE provider = 'email'")
    with op.batch_alter_table('email_tokens') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('email_tokens') as batch_op:
        batch_op.drop_column('user_id')
    with op.batch_alter_table('identities') as batch_op:
        batch_op.drop_column('email')
