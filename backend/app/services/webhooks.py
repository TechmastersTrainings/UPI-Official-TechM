"""Outbound merchant webhooks.

Outbox pattern: an event row (`webhook_deliveries`) is written in the same database transaction as
the payment change it describes, so a status change and its notification commit or roll back
together. The worker then delivers due rows.

Signature: `X-TM-Signature: v1=<hex HMAC-SHA256(signing_secret, "{X-TM-Timestamp}.{raw_body}")>`.
Receivers should reject timestamps older than 5 minutes and compare signatures in constant time.

Retries: after a failed attempt the next one is due 1m, 5m, 15m, 1h, 6h, 24h, 24h later; after
8 failed attempts the delivery is FAILED and can be redelivered from the console.

SSRF: the destination is re-checked at send time. Its hostname must resolve only to public IP
addresses (private/loopback targets are allowed for TEST only in development), and redirects
are not followed.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import time
from datetime import timedelta
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_str
from app.core.errors import AppError, NotFound
from app.db.types import utcnow
from app.models import Payment, WebhookConfiguration, WebhookDelivery
from app.models.enums import PaymentStatus as S
from app.models.enums import WebhookDeliveryStatus as D

log = logging.getLogger(__name__)

RETRY_DELAYS = [60, 300, 900, 3600, 21_600, 86_400, 86_400]
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
CLAIM_LEASE = timedelta(minutes=2)
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
USER_AGENT = "TechMasters-Webhooks/1.0"

STATUS_EVENTS = {
    S.INITIATED: "payment.initiated",
    S.PENDING: "payment.pending",
    S.PROCESSING: "payment.pending",
    S.SUCCESS: "payment.success",
    S.FAILED: "payment.failed",
    S.EXPIRED: "payment.expired",
    S.CANCELLED: "payment.cancelled",
    S.REFUND_PENDING: "payment.refund_initiated",
    S.PARTIALLY_REFUNDED: "payment.refunded",
    S.REFUNDED: "payment.refunded",
}

# Test seams: tests replace these to avoid real DNS / network.
_transport: httpx.BaseTransport | None = None
_resolve = socket.getaddrinfo


def _config(db: Session, merchant_id: str, environment: str) -> WebhookConfiguration | None:
    return db.scalar(select(WebhookConfiguration).where(
        WebhookConfiguration.merchant_id == merchant_id, WebhookConfiguration.environment == environment,
    ))


def _new_event_id() -> str:
    return "evt_" + secrets.token_urlsafe(18)


def enqueue_payment_event(db: Session, payment: Payment, event_type: str) -> WebhookDelivery | None:
    """Queue `event_type` for the payment's merchant if they subscribed to it. Not committed here."""
    cfg = _config(db, payment.merchant_id, payment.environment)
    if cfg is None or not cfg.is_active or event_type not in (cfg.events or []):
        return None
    from app.schemas.payment import PaymentOut  # local import: schemas import services indirectly

    now = utcnow()
    event_id = _new_event_id()
    payload = {
        "id": event_id,
        "type": event_type,
        "created_at": now.isoformat(),
        "environment": payment.environment,
        "data": {"payment": PaymentOut.of(payment).model_dump(mode="json")},
    }
    delivery = WebhookDelivery(
        event_id=event_id, event_type=event_type, merchant_id=payment.merchant_id, environment=payment.environment,
        payment_id=payment.id, url=payment.webhook_url or cfg.url, payload=payload, status=D.PENDING,
        next_attempt_at=now, created_at=now, updated_at=now,
    )
    db.add(delivery)
    return delivery


def enqueue_for_status(db: Session, payment: Payment, status: str) -> None:
    event = STATUS_EVENTS.get(status)
    if event:
        enqueue_payment_event(db, payment, event)


def serialize(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"v1={mac}"


class DestinationRefused(Exception):
    pass


def check_destination(url: str, environment: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise DestinationRefused("invalid URL")
    relaxed = environment == "TEST" and get_settings().is_dev_like
    if p.scheme != "https" and not relaxed:
        raise DestinationRefused("https is required")
    try:
        infos = _resolve(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise DestinationRefused(f"DNS lookup failed: {exc.strerror or exc}") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise DestinationRefused("host did not resolve")
    for addr in addresses:
        ip = ipaddress.ip_address(addr.split("%")[0])
        if not ip.is_global and not relaxed:
            raise DestinationRefused("host resolves to a non-public address")


def _record_failure(delivery: WebhookDelivery, error: str, *, retry: bool) -> None:
    delivery.last_error = error[:500]
    if retry and delivery.attempt_count < MAX_ATTEMPTS:
        delivery.status = D.RETRYING
        delivery.next_attempt_at = utcnow() + timedelta(seconds=RETRY_DELAYS[delivery.attempt_count - 1])
    else:
        delivery.status = D.FAILED
        delivery.next_attempt_at = None


def deliver(db: Session, delivery: WebhookDelivery) -> WebhookDelivery:
    """Make one delivery attempt and record the outcome. Commits."""
    retry = delivery.event_type != "webhook.test"  # test events report their result once, no retries
    delivery.attempt_count += 1
    delivery.last_attempt_at = utcnow()
    delivery.last_response_code = None
    delivery.last_response_body = None
    cfg = _config(db, delivery.merchant_id, delivery.environment)
    if cfg is None:
        _record_failure(delivery, "Webhook endpoint is no longer configured", retry=False)
        db.commit()
        return delivery

    try:
        check_destination(delivery.url, delivery.environment)
        body = serialize(delivery.payload)
        ts = int(time.time())
        headers = {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "X-TM-Event-Id": delivery.event_id,
            "X-TM-Event-Type": delivery.event_type,
            "X-TM-Timestamp": str(ts),
            "X-TM-Signature": sign(decrypt_str(cfg.signing_secret_enc), ts, body),
        }
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False, transport=_transport) as client:
            response = client.post(delivery.url, content=body, headers=headers)
        delivery.last_response_code = response.status_code
        delivery.last_response_body = response.text[:1000]
        if 200 <= response.status_code < 300:
            delivery.status = D.DELIVERED
            delivery.delivered_at = utcnow()
            delivery.next_attempt_at = None
            delivery.last_error = None
            if delivery.event_type == "webhook.test" and delivery.url == cfg.url:
                cfg.validated_at = utcnow()
        else:
            _record_failure(delivery, f"Endpoint responded with HTTP {response.status_code}", retry=retry)
    except DestinationRefused as exc:
        _record_failure(delivery, f"Destination refused: {exc}", retry=retry)
    except httpx.HTTPError as exc:
        _record_failure(delivery, f"{type(exc).__name__}: {exc}"[:500], retry=retry)
    db.commit()
    return delivery


def deliver_due(db: Session, *, batch_size: int = 50) -> int:
    """Worker job. Claims due rows with a short lease (so the HTTP calls happen without holding row
    locks), then attempts each."""
    now = utcnow()
    rows = db.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.status.in_([D.PENDING, D.RETRYING]), WebhookDelivery.next_attempt_at <= now)
        .order_by(WebhookDelivery.next_attempt_at).limit(batch_size).with_for_update(skip_locked=True)
    ).all()
    for d in rows:
        d.next_attempt_at = now + CLAIM_LEASE
    db.commit()
    for d in rows:
        try:
            deliver(db, d)
        except Exception:
            db.rollback()
            log.exception("webhook_delivery_crashed", extra={"delivery_id": d.id})
    return len(rows)


def send_test(db: Session, merchant_id: str, environment: str) -> WebhookDelivery:
    cfg = _config(db, merchant_id, environment)
    if cfg is None:
        raise NotFound(f"No {environment.lower()} webhook endpoint is configured", code="WEBHOOK_NOT_CONFIGURED")
    now = utcnow()
    event_id = _new_event_id()
    delivery = WebhookDelivery(
        event_id=event_id, event_type="webhook.test", merchant_id=merchant_id, environment=environment,
        url=cfg.url, status=D.PENDING, created_at=now, updated_at=now,
        payload={"id": event_id, "type": "webhook.test", "created_at": now.isoformat(), "environment": environment,
                 "data": {"message": "Test event from TechMasters Payment Gateway. Verify the signature and return 2xx."}},
    )
    db.add(delivery)
    db.flush()
    return deliver(db, delivery)


def redeliver(db: Session, delivery: WebhookDelivery) -> WebhookDelivery:
    """Manual redelivery from the console: one immediate attempt with the original event id and payload."""
    if delivery.status == D.DELIVERED and delivery.event_type == "webhook.test":
        raise AppError("Send a new test event instead", code="WEBHOOK_ALREADY_DELIVERED")
    if delivery.status == D.FAILED:
        delivery.attempt_count = max(0, MAX_ATTEMPTS - 2)  # one manual try plus one automatic retry
    return deliver(db, delivery)


def list_for(db: Session, merchant_id: str, environment: str | None, payment_id: str | None,
             status: str | None, page: int, page_size: int):
    from sqlalchemy import func

    conds = [WebhookDelivery.merchant_id == merchant_id]
    if environment:
        conds.append(WebhookDelivery.environment == environment)
    if payment_id:
        conds.append(WebhookDelivery.payment_id == payment_id)
    if status:
        conds.append(WebhookDelivery.status == status)
    total = db.scalar(select(func.count()).select_from(WebhookDelivery).where(*conds)) or 0
    rows = db.scalars(select(WebhookDelivery).where(*conds).order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return rows, total
