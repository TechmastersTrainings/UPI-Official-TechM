"""Refunds.

* Only paid payments (SUCCESS / PARTIALLY_REFUNDED) can be refunded, never more than what remains,
  and one refund at a time per payment (the payment sits in REFUND_PENDING meanwhile). Optimistic
  locking on the payment makes concurrent refund requests safe.
* `Idempotency-Key` is required, with the same replay / conflict rules as payment creation.
* The refund row and REFUND_PENDING are committed *before* the provider is called, so a crash
  mid-call leaves a visible, pollable refund rather than a silent one.
* The outcome only comes from the provider (status API or callback). A successful refund writes a
  REFUND ledger row and moves the payment to PARTIALLY_REFUNDED / REFUNDED; a failed one returns
  the payment to its previous status and notifies `payment.refund_failed`.
"""

import hashlib
import json
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import AppError, Conflict, NotFound
from app.db.types import utcnow
from app.models import Merchant, Payment, Refund, Transaction
from app.models.enums import EventSource, PaymentStatus as S, RefundStatus as R, TransactionType, VerificationMethod
from app.providers.base import ProviderError, RefundResult, RefundSnapshot, RefundState
from app.schemas.payment import RefundCreate, RefundOut
from app.services import payment_state, payments, verification

log = logging.getLogger(__name__)

REFUNDABLE = frozenset({S.SUCCESS, S.PARTIALLY_REFUNDED})
POLL_DELAYS = [5, 10, 30, 60, 300, 900, 3600]  # refunds can take hours at real banks
POLL_LEASE = timedelta(minutes=1)


def _hash(body: RefundCreate) -> str:
    return hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _by_key(db: Session, merchant_id: str, environment: str, key: str) -> Refund | None:
    return db.scalar(select(Refund).where(Refund.merchant_id == merchant_id, Refund.environment == environment,
                                          Refund.idempotency_key == key))


def _replay(existing: Refund, digest: str) -> tuple[Refund, bool]:
    if existing.request_hash != digest:
        raise Conflict("This Idempotency-Key was already used with a different request body",
                       code="IDEMPOTENCY_CONFLICT", details={"refund_id": existing.id})
    return existing, True


def _out(refund: Refund) -> dict:
    return {"refund": RefundOut.model_validate(refund).model_dump(mode="json")}


def _snapshot(db: Session, refund: Refund, payment: Payment) -> RefundSnapshot:
    attempt = verification.latest_session(db, payment.id)
    return RefundSnapshot(
        refund_id=refund.id, payment_id=payment.id, session_ref=attempt.provider_session_ref if attempt else None,
        provider_transaction_id=payment.provider_transaction_id or "", amount=refund.amount, currency=refund.currency,
        provider_refund_ref=refund.provider_refund_ref,
    )


def create(db: Session, merchant: Merchant, environment: str, body: RefundCreate, idempotency_key: str, *,
           source: str, user_id: str | None = None) -> tuple[Refund, bool]:
    digest = _hash(body)
    existing = _by_key(db, merchant.id, environment, idempotency_key)
    if existing is not None:
        return _replay(existing, digest)

    payment = payments.get_scoped(db, merchant.id, environment, body.payment_id)
    if payment.status == S.REFUND_PENDING:
        raise Conflict("Another refund for this payment is in progress", code="REFUND_IN_PROGRESS")
    if payment.status not in REFUNDABLE:
        raise Conflict(f"Only paid payments can be refunded (status {payment.status})", code="PAYMENT_NOT_REFUNDABLE")
    remaining = payment.amount - payment.amount_refunded
    amount = body.amount or remaining
    if amount > remaining:
        raise AppError(f"Refund amount exceeds the refundable balance of {remaining} paise",
                       code="REFUND_EXCEEDS_BALANCE", status_code=422, details={"refundable": remaining})
    adapter, _ = verification.adapter_and_context(db, payment)
    from app.models import ProviderConfiguration

    config = db.get(ProviderConfiguration, payment.provider_configuration_id)
    if not config.provider.supports_refunds or not hasattr(adapter, "create_refund"):
        raise Conflict("This payment's provider does not support refunds", code="REFUNDS_UNSUPPORTED")

    refund = Refund(
        payment_id=payment.id, merchant_id=merchant.id, environment=environment, amount=amount,
        currency=payment.currency, status=R.PENDING, reason=body.reason, idempotency_key=idempotency_key,
        request_hash=digest, initiated_by_user_id=user_id,
    )
    db.add(refund)
    try:
        db.flush()
        payment_state.transition(db, payment, S.REFUND_PENDING, source=source,
                                 payload={"refund_id": refund.id, "amount": amount, "reason": body.reason},
                                 webhook_data=_out(refund))
        db.commit()
    except StaleDataError as exc:
        db.rollback()
        raise Conflict("The payment changed while the refund was being created; try again",
                       code="PAYMENT_CONCURRENT_UPDATE") from exc
    except IntegrityError:
        db.rollback()
        existing = _by_key(db, merchant.id, environment, idempotency_key)
        if existing is not None:
            return _replay(existing, digest)
        raise
    _submit(db, refund, payment)
    db.refresh(refund)
    return refund, False


def _submit(db: Session, refund: Refund, payment: Payment) -> None:
    try:
        adapter, ctx = verification.adapter_and_context(db, payment)
        result = adapter.create_refund(ctx, _snapshot(db, refund, payment))
    except (ProviderError, AppError) as exc:
        message = getattr(exc, "message", str(exc))
        log.warning("refund_submit_failed", extra={"refund_id": refund.id, "error": message})
        apply_result(db, refund, RefundResult(RefundState.FAILED, failure_reason=f"Provider rejected the refund: {message}"),
                     source=EventSource.SYSTEM)
        return
    refund.provider_refund_ref = result.provider_refund_ref
    refund.status = R.PROCESSING
    refund.next_poll_at = utcnow() + timedelta(seconds=POLL_DELAYS[0])
    db.commit()
    if result.state != RefundState.PENDING:
        apply_result(db, refund, result, source=EventSource.PROVIDER_POLL)


def apply_result(db: Session, refund: Refund, result: RefundResult, *, source: str) -> Refund:
    """Apply the provider's refund outcome. Idempotent; commits."""
    for _ in range(3):
        try:
            _apply_once(db, refund, result, source=source)
            db.commit()
            db.refresh(refund)
            return refund
        except (StaleDataError, IntegrityError):
            db.rollback()
            db.refresh(refund)
    raise Conflict("Could not apply refund status due to concurrent updates", code="PAYMENT_CONCURRENT_UPDATE")


def _apply_once(db: Session, refund: Refund, result: RefundResult, *, source: str) -> None:
    if refund.status in (R.SUCCESS, R.FAILED) or result.state == RefundState.PENDING:
        return
    payment = db.get(Payment, refund.payment_id)
    db.refresh(payment)
    now = utcnow()
    if result.state == RefundState.SUCCESS:
        if result.amount is not None and result.amount != refund.amount:
            payment_state.record_event(db, payment, "refund.verification_failed", source=source, payload={
                "refund_id": refund.id, "expected": refund.amount, "provider": result.amount})
            refund.next_poll_at = None  # needs an operator; stop polling
            log.error("refund_amount_mismatch", extra={"refund_id": refund.id})
            return
        db.add(Transaction(
            payment_id=payment.id, refund_id=refund.id, merchant_id=payment.merchant_id, environment=payment.environment,
            type=TransactionType.REFUND, amount=refund.amount, currency=refund.currency, provider_code=payment.provider_code,
            provider_transaction_id=result.provider_transaction_id or result.provider_refund_ref or refund.provider_refund_ref,
            verification_method=VerificationMethod.PROVIDER_WEBHOOK if source == EventSource.PROVIDER_CALLBACK
            else VerificationMethod.PROVIDER_API,
            verified_at=now,
        ))
        refund.status = R.SUCCESS
        refund.processed_at = now
        refund.next_poll_at = None
        refund.failure_reason = None
        payment.amount_refunded += refund.amount
        target = S.REFUNDED if payment.amount_refunded >= payment.amount else S.PARTIALLY_REFUNDED
        if payment.status == S.REFUND_PENDING:
            payment_state.transition(db, payment, target, source=source,
                                     payload={"refund_id": refund.id, "amount": refund.amount}, webhook_data=_out(refund))
    else:
        refund.status = R.FAILED
        refund.processed_at = now
        refund.next_poll_at = None
        refund.failure_reason = (result.failure_reason or "Refund failed at the provider")[:500]
        if payment.status == S.REFUND_PENDING:
            back = S.SUCCESS if payment.amount_refunded == 0 else S.PARTIALLY_REFUNDED
            payment_state.transition(db, payment, back, source=source, event_type="payment.refund_failed",
                                     payload={"refund_id": refund.id, "reason": refund.failure_reason},
                                     webhook_event="payment.refund_failed", webhook_data=_out(refund))


def poll(db: Session, refund: Refund) -> Refund:
    payment = db.get(Payment, refund.payment_id)
    try:
        adapter, ctx = verification.adapter_and_context(db, payment)
        result = adapter.fetch_refund_status(ctx, _snapshot(db, refund, payment))
    except (ProviderError, AppError) as exc:
        log.warning("refund_status_unavailable", extra={"refund_id": refund.id, "error": str(exc)})
        result = RefundResult(RefundState.PENDING)
    refund = apply_result(db, refund, result, source=EventSource.PROVIDER_POLL)
    if refund.status == R.PROCESSING:
        refund.poll_count += 1
        refund.next_poll_at = utcnow() + timedelta(seconds=POLL_DELAYS[min(refund.poll_count, len(POLL_DELAYS) - 1)])
        db.commit()
    return refund


def poll_due(db: Session, *, batch_size: int = 100) -> int:
    now = utcnow()
    rows = db.scalars(
        select(Refund).where(Refund.status == R.PROCESSING, Refund.next_poll_at <= now)
        .order_by(Refund.next_poll_at).limit(batch_size).with_for_update(skip_locked=True)
    ).all()
    for r in rows:
        r.next_poll_at = now + POLL_LEASE
    db.commit()
    for r in rows:
        try:
            poll(db, r)
        except Exception:
            db.rollback()
            log.exception("refund_poll_crashed", extra={"refund_id": r.id})
    return len(rows)


def get_scoped(db: Session, merchant_id: str, environment: str | None, refund_id: str) -> Refund:
    r = db.get(Refund, refund_id)
    if r is None or r.merchant_id != merchant_id or (environment and r.environment != environment):
        raise NotFound("Refund not found", code="REFUND_NOT_FOUND")
    return r


def for_payment(db: Session, payment_id: str) -> list[Refund]:
    return list(db.scalars(select(Refund).where(Refund.payment_id == payment_id).order_by(Refund.created_at, Refund.id)))
