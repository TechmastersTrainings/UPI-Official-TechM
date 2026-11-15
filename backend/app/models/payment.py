from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, id_column
from app.db.types import UTCDateTime, utcnow
from app.models.enums import (
    AttemptStatus,
    PaymentStatus,
    RefundStatus,
    WebhookDeliveryStatus,
)


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("merchant_id", "environment", "idempotency_key"),
        UniqueConstraint("merchant_id", "environment", "merchant_reference"),
        Index("ix_payments_merchant_env_created", "merchant_id", "environment", "created_at"),
        Index("ix_payments_env_status_created", "environment", "status", "created_at"),
        Index("ix_payments_status_expires", "status", "expires_at"),
    )

    id: Mapped[str] = id_column("pay")
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id", ondelete="RESTRICT"), nullable=False)
    environment: Mapped[str] = mapped_column(String(8), nullable=False)
    merchant_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    order_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units (paise)
    amount_refunded: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=PaymentStatus.CREATED, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    customer_mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    return_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checkout_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    provider_configuration_id: Mapped[str | None] = mapped_column(
        ForeignKey("provider_configurations.id", ondelete="RESTRICT"), nullable=True
    )
    bank_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("merchant_bank_accounts.id", ondelete="RESTRICT"), nullable=True
    )
    provider_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    initiated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Optimistic concurrency guard for state transitions.
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    __mapper_args__ = {"version_id_col": version}


class PaymentAttempt(Base, TimestampMixin):
    __tablename__ = "payment_attempts"

    id: Mapped[str] = id_column("att")
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True, nullable=False)
    provider_code: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_session_ref: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=AttemptStatus.CREATED, nullable=False)
    qr_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    redirect_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    provider_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # redacted snapshot
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Transaction(Base, TimestampMixin):
    """Ledger of verified money movements. A row exists only after provider verification."""

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("provider_code", "provider_transaction_id"),
        Index("ix_transactions_merchant_env_created", "merchant_id", "environment", "created_at"),
    )

    id: Mapped[str] = id_column("txn")
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), index=True, nullable=False)
    refund_id: Mapped[str | None] = mapped_column(ForeignKey("refunds.id", ondelete="RESTRICT"), nullable=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id", ondelete="RESTRICT"), nullable=False)
    environment: Mapped[str] = mapped_column(String(8), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_transaction_id: Mapped[str] = mapped_column(String(100), nullable=False)
    payer_vpa_masked: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)  # e.g. UPI RRN
    verification_method: Mapped[str] = mapped_column(String(32), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class PaymentEvent(Base):
    """Append-only timeline of every status change and notable action on a payment."""

    __tablename__ = "payment_events"
    __table_args__ = (Index("ix_payment_events_payment_created", "payment_id", "created_at"),)

    id: Mapped[str] = id_column("pev")
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class ProviderCallback(Base):
    """Every inbound provider webhook, stored before processing; unique per provider event."""

    __tablename__ = "provider_callbacks"
    __table_args__ = (UniqueConstraint("provider_code", "provider_event_id"),)

    id: Mapped[str] = id_column("pcb")
    provider_code: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(8), nullable=False)
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"), index=True)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    processing_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class Refund(Base, TimestampMixin):
    __tablename__ = "refunds"
    __table_args__ = (
        UniqueConstraint("merchant_id", "environment", "idempotency_key"),
        Index("ix_refunds_merchant_env_created", "merchant_id", "environment", "created_at"),
    )

    id: Mapped[str] = id_column("rfd")
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), index=True, nullable=False)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id", ondelete="RESTRICT"), nullable=False)
    environment: Mapped[str] = mapped_column(String(8), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=RefundStatus.PENDING, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_refund_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    initiated_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class WebhookDelivery(Base, TimestampMixin):
    """Outbound webhook outbox; the worker delivers rows whose next_attempt_at has passed."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("ix_webhook_deliveries_status_next", "status", "next_attempt_at"),
        Index("ix_webhook_deliveries_merchant_env_created", "merchant_id", "environment", "created_at"),
    )

    id: Mapped[str] = id_column("whd")
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False)
    environment: Mapped[str] = mapped_column(String(8), nullable=False)
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"), index=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=WebhookDeliveryStatus.PENDING, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_response_body: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
