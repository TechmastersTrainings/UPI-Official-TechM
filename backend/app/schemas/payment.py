from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.core import validators as v
from app.core.config import get_settings
from app.models.enums import PaymentMethod

Reference = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._\-/:#]+$")
]
MethodLiteral = Literal[PaymentMethod.UPI_QR, PaymentMethod.UPI_INTENT, PaymentMethod.HOSTED]

MAX_NOTES = 15
MAX_NOTE_KEY = 40
MAX_NOTE_VALUE = 256


class Customer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)] | None = None
    mobile: Annotated[str, AfterValidator(v.normalize_mobile)] | None = None
    email: EmailStr | None = None


class PaymentCreate(BaseModel):
    """Create a payment order. Amount is an integer in paise (₹1 = 100)."""

    model_config = ConfigDict(extra="forbid")

    merchant_reference: Reference = Field(description="Your unique id for this payment (unique per environment)")
    order_reference: Reference | None = None
    amount: int = Field(description="Amount in paise")
    currency: Literal["INR"] = "INR"
    payment_method: MethodLiteral = PaymentMethod.HOSTED
    customer: Customer | None = None
    return_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    webhook_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = Field(
        None, description="Overrides the registered endpoint for this payment; must be on the same host"
    )
    expires_in_seconds: int | None = Field(None, description="60–86400; defaults to 900")
    notes: dict[str, str] | None = None

    @field_validator("amount")
    @classmethod
    def _amount(cls, value: int) -> int:
        s = get_settings()
        if value < s.PAYMENT_MIN_AMOUNT or value > s.PAYMENT_MAX_AMOUNT:
            raise ValueError(f"must be between {s.PAYMENT_MIN_AMOUNT} and {s.PAYMENT_MAX_AMOUNT} paise")
        return value

    @field_validator("expires_in_seconds")
    @classmethod
    def _expiry(cls, value: int | None) -> int | None:
        s = get_settings()
        if value is not None and not s.PAYMENT_MIN_EXPIRY_SECONDS <= value <= s.PAYMENT_MAX_EXPIRY_SECONDS:
            raise ValueError(f"must be between {s.PAYMENT_MIN_EXPIRY_SECONDS} and {s.PAYMENT_MAX_EXPIRY_SECONDS}")
        return value

    @field_validator("notes")
    @classmethod
    def _notes(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        if len(value) > MAX_NOTES:
            raise ValueError(f"at most {MAX_NOTES} entries")
        for k, val in value.items():
            if not k or len(k) > MAX_NOTE_KEY or len(val) > MAX_NOTE_VALUE:
                raise ValueError(f"keys must be 1–{MAX_NOTE_KEY} chars and values at most {MAX_NOTE_VALUE} chars")
        return value


class CustomerOut(BaseModel):
    name: str | None
    mobile: str | None
    email: str | None


class PaymentOut(BaseModel):
    """A payment as returned by the gateway API. `status` is set by the backend only; SUCCESS means
    the provider confirmed the payment. Settlement to the bank account is tracked separately."""

    id: str
    environment: str
    merchant_reference: str
    order_reference: str | None
    amount: int
    amount_refunded: int
    currency: str
    status: str
    payment_method: str
    customer: CustomerOut
    return_url: str | None
    webhook_url: str | None
    notes: dict | None
    failure_code: str | None
    failure_reason: str | None
    checkout_url: str = Field(description="Hosted checkout page for this payment; share it with the customer")
    expires_at: datetime
    initiated_at: datetime | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, p) -> "PaymentOut":
        return cls(
            id=p.id, environment=p.environment, merchant_reference=p.merchant_reference,
            order_reference=p.order_reference, amount=p.amount, amount_refunded=p.amount_refunded,
            currency=p.currency, status=p.status, payment_method=p.payment_method,
            customer=CustomerOut(name=p.customer_name, mobile=p.customer_mobile, email=p.customer_email),
            return_url=p.return_url, webhook_url=p.webhook_url, notes=p.notes, failure_code=p.failure_code,
            failure_reason=p.failure_reason, checkout_url=f"{get_settings().checkout_base_url}/{p.checkout_token}",
            expires_at=p.expires_at, initiated_at=p.initiated_at,
            confirmed_at=p.confirmed_at, created_at=p.created_at, updated_at=p.updated_at,
        )


class PaymentStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    merchant_reference: str
    status: str
    amount: int
    amount_refunded: int
    currency: str
    expires_at: datetime
    confirmed_at: datetime | None
    updated_at: datetime


class PaymentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_type: str
    from_status: str | None
    to_status: str | None
    source: str
    payload: dict | None
    created_at: datetime


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    provider_code: str
    method: str
    provider_session_ref: str | None
    status: str
    expires_at: datetime | None
    error_message: str | None
    created_at: datetime


class PaymentDetail(PaymentOut):
    """Console view: the payment plus its provider sessions and full status timeline."""

    merchant_id: str
    merchant_name: str | None = None
    provider_code: str | None
    attempts: list[AttemptOut]
    events: list[PaymentEventOut]
    transactions: list["TransactionOut"] = []
    refunds: list["RefundOut"] = []
    webhook_deliveries: list["WebhookDeliveryOut"] = []


class SessionOut(BaseModel):
    """What the customer needs to pay. In TEST the payloads use the non-payable `tmsandbox://` scheme."""

    attempt_id: str
    provider_code: str
    qr_payload: str | None
    intent_uri: str | None
    redirect_url: str | None
    expires_at: datetime | None

    @classmethod
    def of(cls, a) -> "SessionOut":
        return cls(attempt_id=a.id, provider_code=a.provider_code, qr_payload=a.qr_payload, intent_uri=a.intent_uri,
                   redirect_url=a.redirect_url, expires_at=a.expires_at)


class PaymentSession(BaseModel):
    payment: PaymentOut
    session: SessionOut


class CheckoutView(BaseModel):
    """Public checkout view model. Contains no customer PII and no secrets. `status` is exactly the
    server's status; the page never infers success on its own."""

    payment_id: str
    merchant_name: str
    reference: str
    amount: int
    currency: str
    status: str
    environment: str
    payment_method: str
    expires_at: datetime
    server_time: datetime
    session: SessionOut | None = Field(None, description="Present while the payment is awaiting the customer")
    return_url: str | None = Field(None, description="Present once the payment has reached a final status")


class PaymentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    merchant_id: str
    environment: str
    merchant_reference: str
    order_reference: str | None
    amount: int
    amount_refunded: int
    currency: str
    status: str
    payment_method: str
    customer_name: str | None
    expires_at: datetime
    confirmed_at: datetime | None
    created_at: datetime


class AdminPaymentListItem(PaymentListItem):
    merchant_name: str


class PaymentCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None


class TransactionOut(BaseModel):
    """A verified money movement (ledger row). Provider-confirmed; bank credit is tracked separately."""

    model_config = ConfigDict(from_attributes=True)
    id: str
    payment_id: str
    environment: str
    type: str
    amount: int
    currency: str
    provider_code: str
    provider_transaction_id: str
    bank_reference: str | None
    payer_vpa_masked: str | None
    verification_method: str
    verified_at: datetime


class WebhookDeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    event_type: str
    environment: str
    payment_id: str | None
    url: str
    status: str
    attempt_count: int
    next_attempt_at: datetime | None
    last_attempt_at: datetime | None
    last_response_code: int | None
    last_response_body: str | None
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime


class WebhookDeliveryDetail(WebhookDeliveryOut):
    payload: dict



class RefundCreate(BaseModel):
    """Refund a paid payment, fully (omit `amount`) or partially. One refund can be in progress per payment."""

    model_config = ConfigDict(extra="forbid")
    payment_id: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    amount: int | None = Field(None, ge=1, description="Paise; defaults to the full refundable amount")
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class ConsoleRefundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: int | None = Field(None, ge=1)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class RefundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    payment_id: str
    environment: str
    amount: int
    currency: str
    status: str
    reason: str | None
    provider_refund_ref: str | None
    failure_reason: str | None
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["SUCCESS", "FAILED", "PROCESSING"]


PaymentDetail.model_rebuild()
