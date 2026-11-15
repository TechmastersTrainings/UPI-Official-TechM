"""Payment state machine — the only code allowed to change `payments.status`.

Every transition is checked against two tables:

* TRANSITIONS: which status may follow which.
* ALLOWED_SOURCES: who may cause a given target status. Most importantly, SUCCESS can only come
  from the provider (an authenticated status call or a signature-verified callback). The merchant
  API, the checkout page and admins can never mark a payment as paid.

Each transition appends an immutable `payment_events` row. Concurrent writers are stopped by
optimistic locking (`payments.version`): the UPDATE is `... WHERE id = ? AND version = ?`, so if a
callback and a poll race, exactly one wins and the other gets PAYMENT_CONCURRENT_UPDATE and must
re-read before deciding again.
"""

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import AppError, Conflict
from app.db.types import utcnow
from app.models import Payment, PaymentEvent
from app.models.enums import EventSource as Src
from app.models.enums import PaymentStatus as S

T = TypeVar("T")

TRANSITIONS: dict[str, frozenset[str]] = {
    S.CREATED: frozenset({S.INITIATED, S.CANCELLED, S.EXPIRED}),
    S.INITIATED: frozenset({S.PENDING, S.PROCESSING, S.SUCCESS, S.FAILED, S.EXPIRED}),
    S.PENDING: frozenset({S.PROCESSING, S.SUCCESS, S.FAILED, S.EXPIRED}),
    # Money is moving: only the provider's final answer can end PROCESSING, never a timer.
    S.PROCESSING: frozenset({S.SUCCESS, S.FAILED}),
    S.SUCCESS: frozenset({S.REFUND_PENDING}),
    S.REFUND_PENDING: frozenset({S.SUCCESS, S.PARTIALLY_REFUNDED, S.REFUNDED}),
    S.PARTIALLY_REFUNDED: frozenset({S.REFUND_PENDING}),
    S.FAILED: frozenset(),
    S.EXPIRED: frozenset(),
    S.CANCELLED: frozenset(),
    S.REFUNDED: frozenset(),
}

# The payment leg is over (refund states may still follow SUCCESS).
PAYMENT_LEG_FINAL = frozenset({S.SUCCESS, S.FAILED, S.EXPIRED, S.CANCELLED})

_PROVIDER = frozenset({Src.PROVIDER_CALLBACK, Src.PROVIDER_POLL})

ALLOWED_SOURCES: dict[str, frozenset[str]] = {
    S.INITIATED: frozenset({Src.MERCHANT_API, Src.CHECKOUT}),
    S.PENDING: _PROVIDER,
    S.PROCESSING: _PROVIDER,
    S.SUCCESS: _PROVIDER,
    # SYSTEM covers "the provider rejected the session request" before any customer action.
    S.FAILED: _PROVIDER | {Src.SYSTEM},
    S.EXPIRED: frozenset({Src.SYSTEM}),
    S.CANCELLED: frozenset({Src.MERCHANT_API, Src.ADMIN}),
    S.REFUND_PENDING: frozenset({Src.MERCHANT_API, Src.ADMIN}),
    S.PARTIALLY_REFUNDED: _PROVIDER,
    S.REFUNDED: _PROVIDER,
}
# A refund that the provider rejects returns the payment to its previous collected status.
_REFUND_REVERT = {(S.REFUND_PENDING, S.SUCCESS), (S.REFUND_PENDING, S.PARTIALLY_REFUNDED)}


class InvalidTransition(AppError):
    status_code = 409
    code = "INVALID_STATUS_TRANSITION"


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def transition(
    db: Session,
    payment: Payment,
    target: str,
    *,
    source: str,
    event_type: str | None = None,
    payload: dict | None = None,
) -> PaymentEvent:
    """Move `payment` to `target` and record the event. Does not commit: call `commit_guarded`."""
    current = payment.status
    if not can_transition(current, target):
        raise InvalidTransition(
            f"Payment cannot move from {current} to {target}",
            details={"from": current, "to": target},
        )
    allowed = ALLOWED_SOURCES[target]
    if (current, target) in _REFUND_REVERT:
        allowed = allowed | _PROVIDER
    if source not in allowed:
        raise InvalidTransition(
            f"{source} is not allowed to set status {target}",
            code="TRANSITION_SOURCE_NOT_ALLOWED",
            details={"from": current, "to": target, "source": source},
        )

    now = utcnow()
    payment.status = target
    if target == S.INITIATED and payment.initiated_at is None:
        payment.initiated_at = now
    if target == S.SUCCESS and payment.confirmed_at is None:
        payment.confirmed_at = now
    event = PaymentEvent(
        payment_id=payment.id,
        event_type=event_type or f"payment.{target.lower()}",
        from_status=current,
        to_status=target,
        source=source,
        payload=payload,
        created_at=now,
    )
    db.add(event)
    # Outbox: the merchant notification commits (or rolls back) together with the status change.
    from app.services import webhooks

    webhooks.enqueue_for_status(db, payment, target)
    return event


def record_event(db: Session, payment: Payment, event_type: str, *, source: str, payload: dict | None = None) -> PaymentEvent:
    """Append a non-status event (e.g. payment.created) to the timeline."""
    event = PaymentEvent(
        payment_id=payment.id, event_type=event_type, from_status=None, to_status=payment.status,
        source=source, payload=payload, created_at=utcnow(),
    )
    db.add(event)
    return event


def commit_guarded(db: Session, after: Callable[[], T] | None = None) -> T | None:
    """Commit a transition; turn a lost optimistic-lock race into a 409 the caller can retry."""
    try:
        db.commit()
    except StaleDataError as exc:
        db.rollback()
        raise Conflict(
            "The payment was updated concurrently; fetch it again and retry",
            code="PAYMENT_CONCURRENT_UPDATE",
        ) from exc
    return after() if after else None
