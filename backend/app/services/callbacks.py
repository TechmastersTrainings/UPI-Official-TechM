"""Inbound provider callbacks (provider → gateway webhooks).

1. The raw body is stored in `provider_callbacks` *before* processing; the unique key
   (provider_code, provider_event_id) makes provider retries of a processed event a no-op.
2. The adapter verifies the signature using the configuration of the merchant the session belongs
   to. Invalid signatures are stored (for forensics) and never processed.
3. Verified events go through the verification engine, exactly like status polls.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.db.types import utcnow
from app.models import Payment, PaymentAttempt, ProviderCallback
from app.models.enums import EventSource
from app.providers import registry
from app.providers.base import InvalidSignature
from app.services import verification

log = logging.getLogger(__name__)

_DROP_HEADERS = {"authorization", "cookie", "proxy-authorization"}


@dataclass
class Outcome:
    http_status: int
    result: str  # processed | duplicate | rejected | unknown_session | error
    callback_id: str | None = None


def _store_headers(headers: dict[str, str]) -> dict:
    return {k: v[:500] for k, v in headers.items() if k not in _DROP_HEADERS}


def receive(db: Session, provider_code: str, headers: dict[str, str], body: bytes) -> Outcome:
    cls = registry.adapter_class(provider_code)
    if cls is None:
        raise NotFound("Unknown provider", code="UNKNOWN_PROVIDER")
    try:
        ref = cls.identify_callback(headers, body)
    except InvalidSignature as exc:
        log.warning("provider_callback_unreadable", extra={"provider": provider_code, "error": str(exc)})
        return Outcome(400, "rejected")

    attempt = db.scalar(select(PaymentAttempt).where(
        PaymentAttempt.provider_code == provider_code, PaymentAttempt.provider_session_ref == ref.session_ref,
    ))
    payment = db.get(Payment, attempt.payment_id) if attempt else None

    cb = db.scalar(select(ProviderCallback).where(
        ProviderCallback.provider_code == provider_code, ProviderCallback.provider_event_id == ref.event_id,
    ))
    if cb is not None and cb.processed_at is not None:
        return Outcome(200, "duplicate", cb.id)
    if cb is None:
        cb = ProviderCallback(
            provider_code=provider_code, provider_event_id=ref.event_id,
            environment=payment.environment if payment else "UNKNOWN", payment_id=payment.id if payment else None,
            signature_valid=False, headers=_store_headers(headers), body=body.decode("utf-8", errors="replace"),
        )
        db.add(cb)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # a concurrent delivery of the same event is being handled
            return Outcome(200, "duplicate")

    if payment is None:
        cb.processing_error = "No payment session matches this callback"
        db.commit()
        return Outcome(202, "unknown_session", cb.id)

    try:
        adapter, ctx = verification.adapter_and_context(db, payment)
        event = adapter.verify_callback(ctx, headers, body)
        if event.event_id != ref.event_id or event.session_ref != ref.session_ref:
            raise InvalidSignature("verified content does not match routing fields")
    except InvalidSignature as exc:
        cb.signature_valid = False
        cb.processing_error = f"Rejected: {exc}"[:500]
        db.commit()
        log.warning("provider_callback_bad_signature", extra={"provider": provider_code, "callback_id": cb.id})
        return Outcome(401, "rejected", cb.id)

    cb.signature_valid = True
    db.commit()
    try:
        verification.apply(db, payment, attempt, event.status, source=EventSource.PROVIDER_CALLBACK)
    except Exception as exc:
        db.rollback()
        cb.processing_error = f"{type(exc).__name__}: {exc}"[:500]
        db.commit()
        log.exception("provider_callback_processing_failed", extra={"callback_id": cb.id})
        return Outcome(500, "error", cb.id)  # provider retries; the unprocessed row is re-processed
    cb.processed_at = utcnow()
    cb.processing_error = None
    db.commit()
    return Outcome(200, "processed", cb.id)
