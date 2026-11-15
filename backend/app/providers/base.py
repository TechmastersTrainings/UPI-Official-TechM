"""Provider adapter contract.

The payment engine talks to providers only through this interface and only consumes the
normalised results below. A real provider (a licensed payment aggregator or acquiring bank) is
added as one module implementing PaymentProvider plus a `payment_providers` row; the engine does
not change. Adapters receive the decrypted configuration of exactly one merchant + environment.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class ProviderError(Exception):
    """The provider could not complete the request (network, rejection, bad credentials)."""

    def __init__(self, message: str, *, retryable: bool = True, provider_code: str | None = None):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.provider_code = provider_code


@dataclass(frozen=True)
class ProviderContext:
    provider_code: str
    environment: str
    provider_merchant_id: str | None
    credentials: dict = field(repr=False, default_factory=dict)


@dataclass(frozen=True)
class PaymentSnapshot:
    """What an adapter may know about a payment. No customer PII is passed to providers by default."""

    payment_id: str
    merchant_reference: str
    amount: int  # paise
    currency: str
    payee_name: str
    expires_at: datetime
    method: str


@dataclass(frozen=True)
class SessionResult:
    provider_session_ref: str
    expires_at: datetime
    qr_payload: str | None = None
    intent_uri: str | None = None
    redirect_url: str | None = None
    raw: dict | None = None  # redacted provider response kept for support


class ProviderState(StrEnum):
    AWAITING_CUSTOMER = "AWAITING_CUSTOMER"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"  # session closed and the provider confirms nothing was collected


@dataclass(frozen=True)
class ProviderStatus:
    state: ProviderState
    amount: int | None = None
    currency: str | None = None
    provider_transaction_id: str | None = None
    bank_reference: str | None = None
    failure_reason: str | None = None
    payer_vpa: str | None = field(default=None, repr=False)  # stored masked only
    raw: dict | None = None


class InvalidSignature(Exception):
    """A callback failed signature verification. It is stored and never processed."""


@dataclass(frozen=True)
class CallbackRef:
    """Unverified routing data read from a callback, used only to find which payment (and so which
    merchant's provider configuration) to verify it against."""

    event_id: str
    session_ref: str


@dataclass(frozen=True)
class CallbackEvent:
    """A callback whose signature has been verified."""

    event_id: str
    session_ref: str
    status: ProviderStatus


class RefundState(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RefundSnapshot:
    refund_id: str
    payment_id: str
    session_ref: str | None
    provider_transaction_id: str
    amount: int
    currency: str
    provider_refund_ref: str | None = None


@dataclass(frozen=True)
class RefundResult:
    state: RefundState
    provider_refund_ref: str | None = None
    amount: int | None = None
    provider_transaction_id: str | None = None  # id of the refund money movement, once it succeeded
    failure_reason: str | None = None
    raw: dict | None = None


class PaymentProvider(Protocol):
    code: str
    live_capable: bool

    def create_session(self, ctx: ProviderContext, payment: PaymentSnapshot) -> SessionResult: ...

    def fetch_status(self, ctx: ProviderContext, payment: PaymentSnapshot, session_ref: str,
                     session_expires_at: datetime) -> ProviderStatus: ...

    @classmethod
    def identify_callback(cls, headers: dict[str, str], body: bytes) -> CallbackRef: ...

    def verify_callback(self, ctx: ProviderContext, headers: dict[str, str], body: bytes) -> CallbackEvent:
        """MUST verify the provider's signature and raise InvalidSignature if it doesn't match."""
        ...

    def create_refund(self, ctx: ProviderContext, refund: RefundSnapshot) -> RefundResult: ...

    def fetch_refund_status(self, ctx: ProviderContext, refund: RefundSnapshot) -> RefundResult: ...

    # Phase 7/8 adds: fetch_settlements.
