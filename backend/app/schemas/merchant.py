from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.core import validators as v

Env = Literal["TEST", "LIVE"]
BUSINESS_TYPES = (
    "SOLE_PROPRIETORSHIP", "PARTNERSHIP", "LLP", "PRIVATE_LIMITED", "PUBLIC_LIMITED", "TRUST", "SOCIETY",
    "GOVERNMENT", "INDIVIDUAL", "OTHER",
)
BusinessType = Literal[BUSINESS_TYPES]  # type: ignore[valid-type]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=150)]
LongName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
City = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]
Mobile = Annotated[str, AfterValidator(v.normalize_mobile)]
Ifsc = Annotated[str, AfterValidator(v.normalize_ifsc)]
AccountNumber = Annotated[str, AfterValidator(v.normalize_account_number)]
Vpa = Annotated[str, AfterValidator(v.normalize_vpa)]
Pan = Annotated[str, AfterValidator(v.normalize_pan)]
Gstin = Annotated[str, AfterValidator(v.normalize_gstin)]
Pin = Annotated[str, AfterValidator(v.normalize_pin)]
Website = Annotated[str, StringConstraints(max_length=500), AfterValidator(v.validate_website)]


# ---------- Registration / profile ----------
class BusinessDetails(BaseModel):
    business_name: LongName
    legal_business_name: LongName
    business_email: EmailStr
    mobile: Mobile
    business_type: BusinessType
    website_url: Website | None = None


class AddressDetails(BaseModel):
    address_line1: Line
    address_line2: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    city: City
    state: City
    postal_code: Pin
    country: Literal["IN"] = "IN"


class ContactDetails(BaseModel):
    contact_person_name: Name
    contact_person_email: EmailStr | None = None
    contact_person_mobile: Mobile | None = None
    pan: Pan | None = None
    gstin: Gstin | None = None


class AccountOwner(BaseModel):
    full_name: Name
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class MerchantRegistrationRequest(BaseModel):
    business: BusinessDetails
    address: AddressDetails
    contact: ContactDetails
    owner: AccountOwner


class MerchantProfileUpdate(BaseModel):
    """Partial update; omitted sections are unchanged. business_email is the account identity and
    is changed only by TechMasters support."""

    business_name: LongName | None = None
    legal_business_name: LongName | None = None
    mobile: Mobile | None = None
    business_type: BusinessType | None = None
    website_url: Website | None = None
    address: AddressDetails | None = None
    contact: ContactDetails | None = None


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    address_line1: str
    address_line2: str | None
    city: str
    state: str
    postal_code: str
    country: str
    contact_person_name: str
    contact_person_email: str | None
    contact_person_mobile: str | None
    pan: str | None
    gstin: str | None


class MerchantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    business_name: str
    legal_business_name: str
    business_email: str
    mobile: str
    business_type: str
    website_url: str | None
    status: str
    status_reason: str | None
    api_access_enabled: bool
    live_enabled: bool
    live_enabled_at: datetime | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    profile: ProfileOut | None = None


class ReadinessItem(BaseModel):
    key: str
    label: str
    met: bool
    detail: str | None = None


class LiveReadiness(BaseModel):
    ready: bool
    items: list[ReadinessItem]


# ---------- Bank accounts ----------
class BankAccountCreate(BaseModel):
    environment: Env = "LIVE"
    account_holder_name: Name
    bank_name: Name
    account_number: AccountNumber
    ifsc: Ifsc
    upi_vpa: Vpa | None = None
    make_default: bool = False


class BankAccountUpdate(BaseModel):
    account_holder_name: Name | None = None
    bank_name: Name | None = None
    account_number: AccountNumber | None = None
    ifsc: Ifsc | None = None
    upi_vpa: Vpa | None = None
    clear_upi_vpa: bool = False


class BankAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    merchant_id: str
    environment: str
    account_holder_name: str
    bank_name: str
    account_number_masked: str
    ifsc: str
    upi_vpa: str | None
    is_default: bool
    is_active: bool
    verification_status: str
    verification_note: str | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RevealedAccountNumber(BaseModel):
    id: str
    account_number: str


# ---------- Providers ----------
class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str
    name: str
    supports_upi_qr: bool
    supports_upi_intent: bool
    supports_hosted_checkout: bool
    supports_refunds: bool
    supports_settlement_reports: bool
    is_live_capable: bool
    is_enabled: bool


class ProviderConfigCreate(BaseModel):
    provider_code: Annotated[str, StringConstraints(max_length=32)]
    environment: Env
    provider_merchant_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    # Provider-specific secrets (e.g. {"key_id": "...", "key_secret": "..."}). Encrypted at rest, never returned.
    credentials: dict[str, Annotated[str, StringConstraints(min_length=1, max_length=2000)]] = Field(max_length=20)


class ProviderConfigUpdate(BaseModel):
    provider_merchant_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    credentials: dict[str, Annotated[str, StringConstraints(min_length=1, max_length=2000)]] | None = Field(
        default=None, max_length=20
    )


class ProviderConfigOut(BaseModel):
    id: str
    merchant_id: str
    provider: ProviderOut
    environment: str
    provider_merchant_id: str | None
    credential_fields: list[str]
    status: str
    status_reason: str | None
    submitted_at: datetime | None
    approved_at: datetime | None
    integration_tested_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ---------- API credentials ----------
class CredentialCreate(BaseModel):
    environment: Env
    label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None


class CredentialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    environment: str
    key_id: str
    secret_prefix: str
    label: str | None
    status: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class CredentialWithSecret(CredentialOut):
    key_secret: str = Field(description="Shown exactly once. Store it securely; it cannot be retrieved again.")


class ApiAccessToggle(BaseModel):
    enabled: bool


# ---------- Webhooks ----------
WEBHOOK_EVENTS = (
    "payment.created", "payment.initiated", "payment.pending", "payment.success", "payment.failed",
    "payment.expired", "payment.refund_initiated", "payment.refunded", "settlement.updated",
)
WebhookEvent = Literal[WEBHOOK_EVENTS]  # type: ignore[valid-type]


class WebhookConfigUpsert(BaseModel):
    url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
    events: list[WebhookEvent] = Field(min_length=1)
    is_active: bool = True


class WebhookConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    environment: str
    url: str
    events: list[str]
    secret_prefix: str
    is_active: bool
    validated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WebhookConfigWithSecret(WebhookConfigOut):
    signing_secret: str = Field(description="Shown exactly once. Use it to verify X-TM-Signature.")


# ---------- Logs ----------
class ApiRequestLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    credential_id: str | None
    environment: str | None
    method: str
    path: str
    status_code: int
    latency_ms: int
    ip_address: str | None
    idempotency_key: str | None
    request_id: str | None
    error_code: str | None
    created_at: datetime


# ---------- Admin ----------
class StatusChange(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class ReasonRequired(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class BankVerificationDecision(BaseModel):
    decision: Literal["VERIFIED", "REJECTED"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class MerchantUserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    last_login_at: datetime | None


class MerchantSummaryOut(BaseModel):
    id: str
    business_name: str
    business_email: str
    business_type: str
    status: str
    live_enabled: bool
    api_access_enabled: bool
    created_at: datetime
