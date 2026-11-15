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
    raw: dict | None = None


class PaymentProvider(Protocol):
    code: str
    live_capable: bool

    def create_session(self, ctx: ProviderContext, payment: PaymentSnapshot) -> SessionResult: ...

    def fetch_status(self, ctx: ProviderContext, payment: PaymentSnapshot, session_ref: str,
                     session_expires_at: datetime) -> ProviderStatus: ...

    # Phase 5 adds: parse_callback (must verify the signature), create_refund, fetch_refund_status,
    # fetch_settlements.
