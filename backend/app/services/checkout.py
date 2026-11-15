"""Opening provider sessions (UPI QR / intent) and settling expiry with the provider.

Rules:
* A provider session is opened only for a CREATED payment of a merchant that may still collect
  in that environment, through the provider configuration chosen at creation (still ACTIVE).
* Opening is idempotent: if a session already exists, it is returned instead of opening another.
* After a session exists the customer may have paid, so a payment past its deadline is expired
  only when the provider itself says the session closed without collecting money.
"""

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import AppError, Conflict, Forbidden
from app.db.types import utcnow
from app.models import Merchant, Payment, PaymentAttempt, ProviderConfiguration
from app.models.enums import (
    AttemptStatus,
    Environment,
    MerchantStatus,
    PaymentStatus,
    ProviderConfigStatus,
)
from app.providers import registry
from app.providers.base import ProviderError
from app.services import payment_state, payments, verification

log = logging.getLogger(__name__)

AWAITING_STATUSES = frozenset({PaymentStatus.INITIATED, PaymentStatus.PENDING, PaymentStatus.PROCESSING})


class NotPayable(Conflict):
    code = "PAYMENT_NOT_PAYABLE"


def latest_attempt(db: Session, payment_id: str) -> PaymentAttempt | None:
    return db.scalar(
        select(PaymentAttempt).where(PaymentAttempt.payment_id == payment_id)
        .order_by(PaymentAttempt.created_at.desc(), PaymentAttempt.id.desc()).limit(1)
    )


def attempts(db: Session, payment_id: str) -> list[PaymentAttempt]:
    return list(db.scalars(
        select(PaymentAttempt).where(PaymentAttempt.payment_id == payment_id)
        .order_by(PaymentAttempt.created_at, PaymentAttempt.id)
    ))


def _config_for(db: Session, payment: Payment) -> ProviderConfiguration:
    config = db.get(ProviderConfiguration, payment.provider_configuration_id) if payment.provider_configuration_id else None
    if (
        config is None or config.status != ProviderConfigStatus.ACTIVE or not config.provider.is_enabled
        or config.environment != payment.environment
    ):
        raise registry.ProviderUnavailable("The payment provider for this payment is not available")
    return config


def _check_merchant_can_collect(merchant: Merchant, environment: str) -> None:
    if merchant.status in (MerchantStatus.SUSPENDED, MerchantStatus.REJECTED):
        raise Forbidden("This merchant cannot accept payments right now", code="MERCHANT_NOT_ACTIVE")
    if environment == Environment.LIVE and (not merchant.live_enabled or merchant.status != MerchantStatus.ACTIVE):
        raise Forbidden("This merchant cannot accept live payments right now", code="LIVE_NOT_ENABLED")


def open_session(db: Session, payment: Payment, *, source: str) -> PaymentAttempt:
    payment = payments.expire_if_due(db, payment)
    if payment.status in AWAITING_STATUSES:
        existing = latest_attempt(db, payment.id)
        if existing is not None:
            return existing
    if payment.status != PaymentStatus.CREATED:
        raise NotPayable(f"This payment can no longer be paid (status {payment.status})", details={"status": payment.status})

    # Serialise concurrent "Pay" clicks on MySQL; optimistic locking still guards the commit.
    db.refresh(payment, with_for_update=True)
    if payment.status != PaymentStatus.CREATED:
        db.rollback()
        return open_session(db, payment, source=source)

    merchant = db.get(Merchant, payment.merchant_id)
    _check_merchant_can_collect(merchant, payment.environment)
    config = _config_for(db, payment)
    adapter = registry.get_adapter(config.provider.code, payment.environment, db_live_capable=config.provider.is_live_capable)

    try:
        result = adapter.create_session(registry.context_for(config), verification.snapshot(payment, merchant))
    except ProviderError as exc:
        db.rollback()
        db.add(PaymentAttempt(
            payment_id=payment.id, provider_code=config.provider.code, method=payment.payment_method,
            status=AttemptStatus.FAILED, error_message=exc.message[:500],
        ))
        db.commit()
        log.warning("provider_session_failed", extra={"payment_id": payment.id, "provider": config.provider.code})
        raise AppError("The payment provider is temporarily unavailable; please try again",
                       code="PROVIDER_ERROR", status_code=502) from exc

    attempt = PaymentAttempt(
        payment_id=payment.id, provider_code=config.provider.code, method=payment.payment_method,
        provider_session_ref=result.provider_session_ref, status=AttemptStatus.AWAITING_CUSTOMER,
        qr_payload=result.qr_payload, intent_uri=result.intent_uri, redirect_url=result.redirect_url,
        expires_at=min(result.expires_at, payment.expires_at), provider_response=result.raw,
        next_poll_at=utcnow() + timedelta(seconds=verification.POLL_DELAYS[0]),
    )
    db.add(attempt)
    db.flush()
    payment_state.transition(db, payment, PaymentStatus.INITIATED, source=source,
                             payload={"attempt_id": attempt.id, "provider_session_ref": result.provider_session_ref})
    try:
        db.commit()
    except StaleDataError:
        # Another request opened a session first; use theirs.
        db.rollback()
        db.refresh(payment)
        existing = latest_attempt(db, payment.id)
        if payment.status in AWAITING_STATUSES and existing is not None:
            return existing
        raise Conflict("The payment was updated concurrently; try again", code="PAYMENT_CONCURRENT_UPDATE")
    db.refresh(attempt)
    return attempt


def sync_expiry(db: Session, payment: Payment) -> Payment:
    """Expire an overdue payment. CREATED payments expire directly; payments with a provider session
    are settled by asking the provider (which may also report that the customer did pay)."""
    if payment.status == PaymentStatus.CREATED:
        return payments.expire_if_due(db, payment)
    if payment.status not in (PaymentStatus.INITIATED, PaymentStatus.PENDING) or payment.expires_at > utcnow():
        return payment
    attempt = verification.latest_session(db, payment.id)
    return verification.poll(db, payment, attempt) if attempt else payment


def expire_sessions_due(db: Session, *, batch_size: int = 100) -> int:
    """Worker job: overdue payments with an open session whose regular poll is not due yet."""
    ids = list(db.scalars(
        select(Payment.id)
        .where(Payment.status.in_([PaymentStatus.INITIATED, PaymentStatus.PENDING]), Payment.expires_at <= utcnow())
        .order_by(Payment.expires_at).limit(batch_size)
    ))
    db.rollback()
    expired = 0
    for pid in ids:
        p = db.get(Payment, pid)
        if p is not None and sync_expiry(db, p).status == PaymentStatus.EXPIRED:
            expired += 1
    return expired


def by_token(db: Session, token: str) -> Payment | None:
    if not token or len(token) > 64:
        return None
    return db.scalar(select(Payment).where(Payment.checkout_token == token))
