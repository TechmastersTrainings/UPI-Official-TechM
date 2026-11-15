from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Date, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, id_column
from app.db.types import UTCDateTime
from app.models.enums import ReconciliationStatus, SettlementStatus


class Settlement(Base, TimestampMixin):
    """A settlement batch reported by a provider, optionally confirmed against a bank statement."""

    __tablename__ = "settlements"
    __table_args__ = (
        UniqueConstraint("provider_code", "settlement_reference"),
        Index("ix_settlements_merchant_env_date", "merchant_id", "environment", "settlement_date"),
    )

    id: Mapped[str] = id_column("stl")
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id", ondelete="RESTRICT"), nullable=False)
    environment: Mapped[str] = mapped_column(String(8), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(32), nullable=False)
    settlement_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    settlement_date: Mapped[date] = mapped_column(Date, nullable=False)
    bank_account_id: Mapped[str | None] = mapped_column(ForeignKey("merchant_bank_accounts.id", ondelete="SET NULL"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    gross_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    tax_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    net_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    utr: Mapped[str | None] = mapped_column(String(64), nullable=True)  # bank transfer reference
    status: Mapped[str] = mapped_column(String(16), default=SettlementStatus.PENDING, nullable=False)
    # Set only from bank statement / bank API evidence, never from a provider payment callback.
    bank_credited_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bank_credited_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # PROVIDER_REPORT | BANK_STATEMENT | MANUAL
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ReconciliationRecord(Base, TimestampMixin):
    __tablename__ = "reconciliation_records"
    __table_args__ = (Index("ix_reconciliation_records_status_updated", "status", "updated_at"),)

    id: Mapped[str] = id_column("rec")
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), index=True, nullable=False)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id", ondelete="RESTRICT"), index=True, nullable=False)
    environment: Mapped[str] = mapped_column(String(8), nullable=False)
    settlement_id: Mapped[str | None] = mapped_column(
        ForeignKey("settlements.id", ondelete="SET NULL"), index=True, nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default=ReconciliationStatus.NOT_RECONCILED, nullable=False)
    expected_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settled_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mismatch_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
