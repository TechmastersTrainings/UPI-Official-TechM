"""Phase 6: sandbox provider simulation store; refund status polling schedule.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.db.types

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sandbox_simulations",
        sa.Column("ref", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("session_ref", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("auto_outcome", sa.String(length=16), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("provider_transaction_id", sa.String(length=64), nullable=True),
        sa.Column("decided_at", app.db.types.UTCDateTime(), nullable=True),
        sa.Column("expires_at", app.db.types.UTCDateTime(), nullable=True),
        sa.Column("created_at", app.db.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("ref", name=op.f("pk_sandbox_simulations")),
    )
    op.create_index("ix_sandbox_simulations_session_ref", "sandbox_simulations", ["session_ref"], unique=False)
    with op.batch_alter_table("refunds", schema=None) as batch_op:
        batch_op.add_column(sa.Column("next_poll_at", app.db.types.UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column("poll_count", sa.Integer(), server_default="0", nullable=False))
        batch_op.create_index(batch_op.f("ix_refunds_next_poll_at"), ["next_poll_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("refunds", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_refunds_next_poll_at"))
        batch_op.drop_column("poll_count")
        batch_op.drop_column("next_poll_at")
    op.drop_index("ix_sandbox_simulations_session_ref", table_name="sandbox_simulations")
    op.drop_table("sandbox_simulations")
