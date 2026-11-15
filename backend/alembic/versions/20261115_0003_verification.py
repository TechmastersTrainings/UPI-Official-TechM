"""Phase 5: status-poll scheduling on payment attempts.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.db.types

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("payment_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("next_poll_at", app.db.types.UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column("poll_count", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("last_polled_at", app.db.types.UTCDateTime(), nullable=True))
        batch_op.create_index(batch_op.f("ix_payment_attempts_next_poll_at"), ["next_poll_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("payment_attempts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_payment_attempts_next_poll_at"))
        batch_op.drop_column("last_polled_at")
        batch_op.drop_column("poll_count")
        batch_op.drop_column("next_poll_at")
