"""Verification engine: the only path by which provider information changes a payment.

Inputs are authenticated provider answers: a status API call (PROVIDER_POLL) or a callback whose
signature was verified (PROVIDER_CALLBACK). Before a payment becomes SUCCESS, the provider's
amount, currency and transaction id are cross-checked against the stored payment; any mismatch
blocks the success and is recorded for investigation.

A SUCCESS creates exactly one ledger row (`transactions`, unique per provider transaction id) and a
reconciliation record in NOT_RECONCILED: "provider confirmed" is not "money in the bank".

Money that arrives for a payment that is already EXPIRED / CANCELLED / FAILED, or a second
transaction for an already-paid payment, is never silently applied: it is recorded in the ledger
(it is real money) and flagged INVESTIGATION_REQUIRED for an operator to refund or resolve.
"""

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import AppError
from app.db.types import utcnow
from app.models import (
    Merchant,
    Payment,
    PaymentAttempt,
    PaymentEvent,
    ProviderConfiguration,
    ReconciliationRecord,
    Transaction,
)
from app.models.enums import (
    AttemptStatus,
    EventSource,
    PaymentStatus as S,
    ReconciliationStatus,
    TransactionType,
    VerificationMethod,
)
from app.providers import registry
from app.providers.base import PaymentSnapshot, ProviderError, ProviderState, ProviderStatus
from app.services import payment_state

log = logging.getLogger(__name__)

OPEN = frozenset({S.INITIATED, S.PENDING, S.PROCESSING})
CLOSED_UNPAID = frozenset({S.EXPIRED, S.CANCELLED, S.FAILED})
COLLECTED = frozenset({S.SUCCESS, S.REFUND_PENDING, S.PARTIALLY_REFUNDED, S.REFUNDED})
POLL_DELAYS = [5, 10, 15, 30, 60, 120, 300]  # seconds, by poll count; then every 5 minutes
POLL_LEASE = timedelta(minutes=1)
FINAL_ATTEMPT = frozenset({AttemptStatus.SUCCESS, AttemptStatus.FAILED, AttemptStatus.EXPIRED})


def mask_vpa(vpa: str | None) -> str | None:
    if not vpa or "@" not in vpa:
        return None
    user, _, handle = vpa.partition("@")
    return (user[:2] + "*" * max(2, len(user) - 2) + "@" + handle)[:100]


def snapshot(payment: Payment, merchant: Merchant) -> PaymentSnapshot:
    return PaymentSnapshot(
        payment_id=payment.id, merchant_reference=payment.merchant_reference, amount=payment.amount,
        currency=payment.currency, payee_name=merchant.business_name, expires_at=payment.expires_at,
        method=payment.payment_method,
    )


def adapter_and_context(db: Session, payment: Payment):
    config = db.get(ProviderConfiguration, payment.provider_configuration_id) if payment.provider_configuration_id else None
    if config is None or config.environment != payment.environment:
        raise registry.ProviderUnavailable("The payment's provider configuration is missing")
    adapter = registry.get_adapter(config.provider.code, payment.environment, db_live_capable=config.provider.is_live_capable)
    return adapter, registry.context_for(config)


# ---------------------------------------------------------------- apply
def apply(db: Session, payment: Payment, attempt: PaymentAttempt, status: ProviderStatus, *, source: str) -> Payment:
    """Apply an authenticated provider status to the payment. Idempotent; commits. Retries once on
    a concurrent update, re-deciding against the fresh state."""
    for _ in range(3):
        try:
            _apply_once(db, payment, attempt, status, source=source)
            db.commit()
            db.refresh(payment)
            return payment
        except (StaleDataError, IntegrityError):
            # A concurrent poll/callback changed the payment or recorded the same provider
            # transaction first. Re-read and decide again; the second pass is normally a no-op.
            db.rollback()
            db.refresh(payment)
            db.refresh(attempt)
    raise AppError("Could not apply provider status due to concurrent updates", code="PAYMENT_CONCURRENT_UPDATE",
                   status_code=409)


def _method(source: str) -> str:
    return VerificationMethod.PROVIDER_WEBHOOK if source == EventSource.PROVIDER_CALLBACK else VerificationMethod.PROVIDER_API


def _apply_once(db: Session, payment: Payment, attempt: PaymentAttempt, status: ProviderStatus, *, source: str) -> None:
    state = status.state
    evidence = {"provider_state": state.value, "attempt_id": attempt.id}
    if state == ProviderState.SUCCESS:
        _apply_success(db, payment, attempt, status, source=source)
    elif state == ProviderState.FAILED:
        if payment.status in OPEN:
            payment.failure_code = "PROVIDER_DECLINED"
            payment.failure_reason = (status.failure_reason or "Declined by the payment provider")[:500]
            attempt.status = AttemptStatus.FAILED
            payment_state.transition(db, payment, S.FAILED, source=source,
                                     payload=evidence | {"reason": payment.failure_reason})
    elif state == ProviderState.PROCESSING:
        if payment.status in (S.INITIATED, S.PENDING):
            payment_state.transition(db, payment, S.PROCESSING, source=source, payload=evidence)
    elif state == ProviderState.EXPIRED:
        attempt.status = AttemptStatus.EXPIRED
        if payment.status in (S.INITIATED, S.PENDING) and payment.expires_at <= utcnow():
            payment_state.transition(db, payment, S.EXPIRED, source=EventSource.SYSTEM, payload=evidence)
    # AWAITING_CUSTOMER: nothing to change.


def _investigate(db: Session, payment: Payment, txn: Transaction, reason: str) -> None:
    db.add(ReconciliationRecord(
        transaction_id=txn.id, payment_id=payment.id, merchant_id=payment.merchant_id, environment=payment.environment,
        status=ReconciliationStatus.INVESTIGATION_REQUIRED, expected_amount=payment.amount, mismatch_reason=reason[:500],
    ))
    payment_state.record_event(db, payment, "payment.investigation_required", source=EventSource.SYSTEM,
                               payload={"reason": reason, "transaction_id": txn.id})
    log.error("payment_investigation_required", extra={"payment_id": payment.id, "reason": reason})


def _apply_success(db: Session, payment: Payment, attempt: PaymentAttempt, status: ProviderStatus, *, source: str) -> None:
    mismatches = []
    if status.amount != payment.amount:
        mismatches.append({"field": "amount", "expected": payment.amount, "provider": status.amount})
    if (status.currency or "").upper() != payment.currency:
        mismatches.append({"field": "currency", "expected": payment.currency, "provider": status.currency})
    if not status.provider_transaction_id:
        mismatches.append({"field": "provider_transaction_id", "expected": "present", "provider": None})
    if mismatches:
        # Not applied. Recorded once per distinct answer so repeated polls don't flood the timeline.
        last = db.scalar(
            select(PaymentEvent).where(PaymentEvent.payment_id == payment.id,
                                       PaymentEvent.event_type == "payment.verification_failed")
            .order_by(PaymentEvent.created_at.desc(), PaymentEvent.id.desc()).limit(1)
        )
        if last is None or (last.payload or {}).get("mismatches") != mismatches:
            payment_state.record_event(db, payment, "payment.verification_failed", source=source,
                                       payload={"mismatches": mismatches, "attempt_id": attempt.id})
            log.error("payment_verification_failed", extra={"payment_id": payment.id, "mismatches": mismatches})
        return

    existing = db.scalar(select(Transaction).where(
        Transaction.provider_code == attempt.provider_code,
        Transaction.provider_transaction_id == status.provider_transaction_id,
    ))
    if existing is not None:
        if existing.payment_id != payment.id:
            payment_state.record_event(db, payment, "payment.verification_failed", source=source, payload={
                "mismatches": [{"field": "provider_transaction_id", "expected": "unused",
                                "provider": status.provider_transaction_id}],
            })
        return  # duplicate confirmation of an already recorded transaction: no-op

    now = utcnow()
    txn = Transaction(
        payment_id=payment.id, merchant_id=payment.merchant_id, environment=payment.environment,
        type=TransactionType.PAYMENT, amount=status.amount, currency=payment.currency,
        provider_code=attempt.provider_code, provider_transaction_id=status.provider_transaction_id,
        payer_vpa_masked=mask_vpa(status.payer_vpa), bank_reference=status.bank_reference,
        verification_method=_method(source), verified_at=now,
    )
    db.add(txn)
    db.flush()
    attempt.status = AttemptStatus.SUCCESS

    if payment.status in OPEN:
        payment.provider_transaction_id = status.provider_transaction_id
        payment.failure_code = payment.failure_reason = None
        db.add(ReconciliationRecord(
            transaction_id=txn.id, payment_id=payment.id, merchant_id=payment.merchant_id,
            environment=payment.environment, status=ReconciliationStatus.NOT_RECONCILED, expected_amount=payment.amount,
        ))
        payment_state.transition(db, payment, S.SUCCESS, source=source, payload={
            "provider_state": "SUCCESS", "attempt_id": attempt.id, "transaction_id": txn.id,
            "provider_transaction_id": status.provider_transaction_id, "bank_reference": status.bank_reference,
            "verification_method": txn.verification_method,
        })
    elif payment.status in CLOSED_UNPAID:
        _investigate(db, payment, txn, f"Provider confirmed a payment after it was {payment.status}")
    elif payment.status in COLLECTED:
        _investigate(db, payment, txn, "Provider confirmed a second transaction for an already paid payment")
    else:
        _investigate(db, payment, txn, f"Provider confirmed a payment in unexpected status {payment.status}")


# ---------------------------------------------------------------- polling
def _schedule_next(attempt: PaymentAttempt) -> None:
    now = utcnow()
    attempt.last_polled_at = now
    attempt.poll_count += 1
    if attempt.status in FINAL_ATTEMPT:
        attempt.next_poll_at = None
    else:
        delay = POLL_DELAYS[min(attempt.poll_count, len(POLL_DELAYS) - 1)]
        attempt.next_poll_at = now + timedelta(seconds=delay)


def poll(db: Session, payment: Payment, attempt: PaymentAttempt) -> Payment:
    """Ask the provider for this session's status and apply the answer."""
    if attempt.provider_session_ref is None:
        return payment
    try:
        adapter, ctx = adapter_and_context(db, payment)
        merchant = db.get(Merchant, payment.merchant_id)
        status = adapter.fetch_status(ctx, snapshot(payment, merchant), attempt.provider_session_ref,
                                      attempt.expires_at or payment.expires_at)
    except (ProviderError, AppError) as exc:
        log.warning("provider_status_unavailable", extra={"payment_id": payment.id, "error": str(exc)})
        _schedule_next(attempt)
        db.commit()
        return payment
    payment = apply(db, payment, attempt, status, source=EventSource.PROVIDER_POLL)
    db.refresh(attempt)
    _schedule_next(attempt)
    db.commit()
    return payment


def latest_session(db: Session, payment_id: str) -> PaymentAttempt | None:
    return db.scalar(
        select(PaymentAttempt).where(PaymentAttempt.payment_id == payment_id, PaymentAttempt.provider_session_ref.is_not(None))
        .order_by(PaymentAttempt.created_at.desc(), PaymentAttempt.id.desc()).limit(1)
    )


def verify_now(db: Session, payment: Payment) -> Payment:
    """Merchant-requested status check (`POST /payments/{id}/verify`)."""
    if payment.status not in OPEN:
        return payment
    attempt = latest_session(db, payment.id)
    return poll(db, payment, attempt) if attempt else payment


def poll_due(db: Session, *, batch_size: int = 100) -> int:
    """Worker job: poll open sessions whose next check is due. Rows are claimed with a lease first so
    provider calls happen without holding database locks."""
    now = utcnow()
    rows = db.scalars(
        select(PaymentAttempt)
        .where(PaymentAttempt.status == AttemptStatus.AWAITING_CUSTOMER, PaymentAttempt.next_poll_at <= now)
        .order_by(PaymentAttempt.next_poll_at).limit(batch_size).with_for_update(skip_locked=True)
    ).all()
    for a in rows:
        a.next_poll_at = now + POLL_LEASE
    db.commit()
    for a in rows:
        payment = db.get(Payment, a.payment_id)
        if payment is None or payment.status not in OPEN:
            a.next_poll_at = None
            db.commit()
            continue
        try:
            poll(db, payment, a)
        except Exception:
            db.rollback()
            log.exception("status_poll_crashed", extra={"attempt_id": a.id})
    return len(rows)
