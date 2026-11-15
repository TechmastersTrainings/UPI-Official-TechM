from datetime import datetime

from sqlalchemy import BigInteger, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow


class SandboxSimulation(Base):
    """State of the simulated provider (the sandbox's own "provider-side" records).

    It is deliberately separate from the gateway's payment tables: the gateway learns about outcomes
    only through the sandbox adapter's status API and signed callbacks, exactly as with a real provider.
    The first decided outcome is final, so callbacks and polls always agree."""

    __tablename__ = "sandbox_simulations"
    __table_args__ = (Index("ix_sandbox_simulations_session_ref", "session_ref"),)

    ref: Mapped[str] = mapped_column(String(64), primary_key=True)  # session or refund reference
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # PAYMENT | REFUND
    session_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)  # refunds: the paid session
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    auto_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
