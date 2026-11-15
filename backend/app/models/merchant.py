from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, id_column
from app.db.types import UTCDateTime
from app.models.enums import (
    CredentialStatus,
    MerchantStatus,
    ProviderConfigStatus,
    VerificationStatus,
)


class Merchant(Base, TimestampMixin):
    __tablename__ = "merchants"

    id: Mapped[str] = id_column("mer")
    business_name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_business_name: Mapped[str] = mapped_column(String(200), nullable=False)
    business_email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    mobile: Mapped[str] = mapped_column(String(20), nullable=False)
    business_type: Mapped[str] = mapped_column(String(50), nullable=False)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=MerchantStatus.PENDING_REVIEW, index=True, nullable=False)
    status_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Gateway API on/off switch, controlled by merchant admin and Super Admin.
    api_access_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Only Super Admin can set this, and only when every live prerequisite is satisfied.
    live_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    live_enabled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # use_alter: users.merchant_id references merchants, so this FK is added after both tables exist.
    approved_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", use_alter=True), nullable=True
    )

    profile: Mapped["MerchantProfile"] = relationship(back_populates="merchant", uselist=False)


class MerchantProfile(Base, TimestampMixin):
    __tablename__ = "merchant_profiles"

    id: Mapped[str] = id_column("mpr")
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    address_line1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(10), nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="IN", nullable=False)
    contact_person_name: Mapped[str] = mapped_column(String(150), nullable=False)
    contact_person_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_person_mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)

    merchant: Mapped[Merchant] = relationship(back_populates="profile")


class PaymentProvider(Base, TimestampMixin):
    __tablename__ = "payment_providers"

    id: Mapped[str] = id_column("prv")
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    supports_upi_qr: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supports_upi_intent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supports_hosted_checkout: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supports_refunds: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supports_settlement_reports: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # False for the sandbox simulator; the registry refuses LIVE use when False.
    is_live_capable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ProviderConfiguration(Base, TimestampMixin):
    __tablename__ = "provider_configurations"
    __table_args__ = (UniqueConstraint("merchant_id", "provider_id", "environment"),)

    id: Mapped[str] = id_column("pcf")
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    provider_id: Mapped[str] = mapped_column(ForeignKey("payment_providers.id", ondelete="RESTRICT"), nullable=False)
    environment: Mapped[str] = mapped_column(String(8), nullable=False)
    provider_merchant_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    credentials_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=ProviderConfigStatus.DRAFT, nullable=False)
    status_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    integration_tested_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    approved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    provider: Mapped[PaymentProvider] = relationship(lazy="joined")


class MerchantBankAccount(Base, TimestampMixin):
    __tablename__ = "merchant_bank_accounts"
    __table_args__ = (
        UniqueConstraint("merchant_id", "environment", "account_fingerprint", name="uq_bank_accounts_merchant_env_fingerprint"),
    )

    id: Mapped[str] = id_column("bac")
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    environment: Mapped[str] = mapped_column(String(8), nullable=False)
    provider_configuration_id: Mapped[str | None] = mapped_column(
        ForeignKey("provider_configurations.id", ondelete="SET NULL"), nullable=True
    )
    account_holder_name: Mapped[str] = mapped_column(String(150), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(150), nullable=False)
    account_number_enc: Mapped[str] = mapped_column(Text, nullable=False)
    account_number_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    # keyed_hash(IFSC + account number): detects duplicates without decrypting.
    account_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    ifsc: Mapped[str] = mapped_column(String(11), nullable=False)
    upi_vpa: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(32), default=VerificationStatus.UNVERIFIED, nullable=False
    )
    verification_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ApiCredential(Base, TimestampMixin):
    __tablename__ = "api_credentials"

    id: Mapped[str] = id_column("crd")
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    environment: Mapped[str] = mapped_column(String(8), nullable=False)
    key_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=CredentialStatus.ACTIVE, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class WebhookConfiguration(Base, TimestampMixin):
    __tablename__ = "webhook_configurations"
    __table_args__ = (UniqueConstraint("merchant_id", "environment"),)

    id: Mapped[str] = id_column("whc")
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False)
    environment: Mapped[str] = mapped_column(String(8), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    signing_secret_enc: Mapped[str] = mapped_column(Text, nullable=False)
    secret_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    events: Mapped[list] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    validated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
