"""Payment orders: creation (idempotent), lookup, cancellation and expiry.

Isolation: every query is scoped by (merchant_id, environment), and the environment comes from the
API key that authenticated the request, so a test key can never see or change a live payment.
"""

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core import validators as v
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound
from app.db.types import utcnow
from app.models import (
    ApiCredential,
    Merchant,
    MerchantBankAccount,
    Payment,
    PaymentEvent,
    PaymentProvider,
    ProviderConfiguration,
    WebhookConfiguration,
)
from app.models.enums import (
    Environment,
    EventSource,
    PaymentMethod,
    PaymentStatus,
    ProviderConfigStatus,
    VerificationStatus,
)
from app.schemas.payment import PaymentCreate
from app.services import payment_state

log = logging.getLogger(__name__)

_METHOD_FLAG = {
    PaymentMethod.UPI_QR: "supports_upi_qr",
    PaymentMethod.UPI_INTENT: "supports_upi_intent",
    PaymentMethod.HOSTED: "supports_hosted_checkout",
}


class IdempotencyConflict(Conflict):
    code = "IDEMPOTENCY_CONFLICT"


def request_hash(body: PaymentCreate) -> str:
    """Hash of the validated, normalised request so that key order and whitespace don't matter."""
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class CreateResult:
    payment: Payment
    replayed: bool


def _by_idempotency_key(db: Session, merchant_id: str, environment: str, key: str) -> Payment | None:
    return db.scalar(select(Payment).where(
        Payment.merchant_id == merchant_id, Payment.environment == environment, Payment.idempotency_key == key,
    ))


def _replay(existing: Payment, digest: str) -> CreateResult:
    if existing.request_hash != digest:
        raise IdempotencyConflict(
            "This Idempotency-Key was already used with a different request body",
            details={"payment_id": existing.id},
        )
    return CreateResult(existing, replayed=True)


def _replay_or_duplicate(db: Session, merchant_id: str, environment: str, key: str, digest: str) -> CreateResult:
    """The merchant_reference is taken. If a concurrent request with the same Idempotency-Key took it
    (it committed after our first lookup), this is a retry: replay it. Otherwise it's a real duplicate."""
    existing = _by_idempotency_key(db, merchant_id, environment, key)
    if existing is not None:
        return _replay(existing, digest)
    raise Conflict("A payment with this merchant_reference already exists", code="DUPLICATE_MERCHANT_REFERENCE")


def _select_provider(db: Session, merchant_id: str, environment: str, method: str) -> ProviderConfiguration:
    configs = db.scalars(
        select(ProviderConfiguration)
        .join(PaymentProvider, PaymentProvider.id == ProviderConfiguration.provider_id)
        .where(
            ProviderConfiguration.merchant_id == merchant_id,
            ProviderConfiguration.environment == environment,
            ProviderConfiguration.status == ProviderConfigStatus.ACTIVE,
            PaymentProvider.is_enabled.is_(True),
        )
        .order_by(ProviderConfiguration.approved_at, ProviderConfiguration.created_at)
    ).all()
    if environment == Environment.LIVE:
        # Defence in depth: activation already requires a live-capable provider.
        configs = [c for c in configs if c.provider.is_live_capable]
    if not configs:
        raise Conflict(f"No active payment provider for {environment.lower()} mode", code="NO_ACTIVE_PROVIDER")
    for c in configs:
        if getattr(c.provider, _METHOD_FLAG[method]):
            return c
    raise AppError(f"Payment method {method} is not available for this merchant", code="PAYMENT_METHOD_UNAVAILABLE",
                   status_code=422)


def _settlement_account(db: Session, merchant_id: str, environment: str) -> MerchantBankAccount | None:
    account = db.scalar(select(MerchantBankAccount).where(
        MerchantBankAccount.merchant_id == merchant_id, MerchantBankAccount.environment == environment,
        MerchantBankAccount.is_default.is_(True), MerchantBankAccount.is_active.is_(True),
    ))
    if environment == Environment.LIVE and (account is None or account.verification_status != VerificationStatus.VERIFIED):
        raise Conflict("A verified default bank account is required for live payments",
                       code="SETTLEMENT_ACCOUNT_NOT_VERIFIED")
    return account


def _check_urls(db: Session, merchant_id: str, environment: str, body: PaymentCreate) -> None:
    errors = []
    if body.return_url:
        try:
            v.validate_return_url(body.return_url, environment=environment)
        except ValueError as exc:
            errors.append({"field": "return_url", "message": str(exc)})
    if body.webhook_url:
        registered = db.scalar(select(WebhookConfiguration).where(
            WebhookConfiguration.merchant_id == merchant_id, WebhookConfiguration.environment == environment,
        ))
        try:
            v.validate_webhook_url(body.webhook_url, environment=environment,
                                   allow_insecure_local=get_settings().is_dev_like)
            if registered is None:
                raise ValueError(f"register a {environment.lower()} webhook endpoint in the console first")
            if not v.same_origin(body.webhook_url, registered.url):
                raise ValueError("must use the same scheme, host and port as the registered webhook endpoint")
        except ValueError as exc:
            errors.append({"field": "webhook_url", "message": str(exc)})
    if errors:
        raise AppError("Request validation failed", code="VALIDATION_ERROR", status_code=422, details=errors)


def create(db: Session, cred: ApiCredential, merchant: Merchant, body: PaymentCreate, idempotency_key: str) -> CreateResult:
    env = cred.environment
    digest = request_hash(body)

    existing = _by_idempotency_key(db, merchant.id, env, idempotency_key)
    if existing is not None:
        return _replay(existing, digest)

    _check_urls(db, merchant.id, env, body)
    config = _select_provider(db, merchant.id, env, body.payment_method)
    account = _settlement_account(db, merchant.id, env)

    if db.scalar(select(Payment.id).where(
        Payment.merchant_id == merchant.id, Payment.environment == env,
        Payment.merchant_reference == body.merchant_reference,
    )):
        return _replay_or_duplicate(db, merchant.id, env, idempotency_key, digest)

    s = get_settings()
    now = utcnow()
    customer = body.customer
    payment = Payment(
        merchant_id=merchant.id,
        environment=env,
        merchant_reference=body.merchant_reference,
        order_reference=body.order_reference,
        amount=body.amount,
        currency=body.currency,
        status=PaymentStatus.CREATED,
        payment_method=body.payment_method,
        customer_name=customer.name if customer else None,
        customer_mobile=customer.mobile if customer else None,
        customer_email=str(customer.email) if customer and customer.email else None,
        return_url=body.return_url,
        webhook_url=body.webhook_url,
        notes=body.notes,
        expires_at=now + timedelta(seconds=body.expires_in_seconds or s.PAYMENT_DEFAULT_EXPIRY_SECONDS),
        idempotency_key=idempotency_key,
        request_hash=digest,
        checkout_token=secrets.token_urlsafe(32),
        provider_configuration_id=config.id,
        provider_code=config.provider.code,
        bank_account_id=account.id if account else None,
        created_at=now,
        updated_at=now,
    )
    db.add(payment)
    try:
        db.flush()
        payment_state.record_event(db, payment, "payment.created", source=EventSource.MERCHANT_API,
                                   payload={"key_id": cred.key_id, "amount": payment.amount})
        db.commit()
    except IntegrityError:
        # Lost a race with a concurrent request: same Idempotency-Key or same merchant_reference.
        db.rollback()
        return _replay_or_duplicate(db, merchant.id, env, idempotency_key, digest)
    return CreateResult(payment, replayed=False)


def expire_if_due(db: Session, payment: Payment, now: datetime | None = None) -> Payment:
    """Expire a payment that no customer has started paying once its deadline passes.

    Only CREATED payments are expired here: once a provider session exists (INITIATED and later),
    the customer may already have paid, so expiry has to ask the provider first. That check is
    part of the verification worker (Phase 5)."""
    now = now or utcnow()
    if payment.status != PaymentStatus.CREATED or payment.expires_at > now:
        return payment
    payment_state.transition(db, payment, PaymentStatus.EXPIRED, source=EventSource.SYSTEM,
                             payload={"expires_at": payment.expires_at.isoformat()})
    try:
        db.commit()
    except StaleDataError:
        db.rollback()  # someone else moved it first; their state wins
    db.refresh(payment)
    return payment


def expire_due(db: Session, *, now: datetime | None = None, batch_size: int = 200) -> int:
    """Worker job: expire overdue CREATED payments. Rows locked by another worker are skipped
    (`FOR UPDATE SKIP LOCKED` on MySQL 8), so several workers can run safely."""
    now = now or utcnow()
    expired = 0
    while True:
        rows = db.scalars(
            select(Payment)
            .where(Payment.status == PaymentStatus.CREATED, Payment.expires_at <= now)
            .order_by(Payment.expires_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        if not rows:
            db.rollback()
            return expired
        for p in rows:
            payment_state.transition(db, p, PaymentStatus.EXPIRED, source=EventSource.SYSTEM,
                                     payload={"expires_at": p.expires_at.isoformat()})
        try:
            db.commit()
            expired += len(rows)
        except StaleDataError:
            db.rollback()
            log.warning("expiry_batch_conflict", extra={"batch": len(rows)})
            return expired
        if len(rows) < batch_size:
            return expired


def get_scoped(db: Session, merchant_id: str, environment: str | None, payment_id: str) -> Payment:
    p = db.get(Payment, payment_id)
    if p is None or p.merchant_id != merchant_id or (environment and p.environment != environment):
        raise NotFound("Payment not found", code="PAYMENT_NOT_FOUND")
    return expire_if_due(db, p)


def cancel(db: Session, payment: Payment, *, source: str, reason: str | None, actor: str) -> Payment:
    """Cancel a payment the customer has not started paying. Repeating the call is harmless."""
    if payment.status == PaymentStatus.CANCELLED:
        return payment
    if payment.status != PaymentStatus.CREATED:
        raise payment_state.InvalidTransition(
            f"Only payments in CREATED status can be cancelled (current: {payment.status})",
            code="PAYMENT_NOT_CANCELLABLE", details={"status": payment.status},
        )
    payment_state.transition(db, payment, PaymentStatus.CANCELLED, source=source,
                             payload={"reason": reason, "by": actor})
    payment_state.commit_guarded(db)
    db.refresh(payment)
    return payment


def events(db: Session, payment_id: str) -> list[PaymentEvent]:
    return list(db.scalars(
        select(PaymentEvent).where(PaymentEvent.payment_id == payment_id)
        .order_by(PaymentEvent.created_at, PaymentEvent.id)
    ))


@dataclass
class PaymentFilter:
    merchant_id: str | None = None
    environment: str | None = None
    status: str | None = None
    q: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


def search(db: Session, f: PaymentFilter, page: int, page_size: int, *, with_merchant: bool = False):
    conds = []
    if f.merchant_id:
        conds.append(Payment.merchant_id == f.merchant_id)
    if f.environment:
        conds.append(Payment.environment == f.environment)
    if f.status:
        conds.append(Payment.status == f.status)
    if f.created_from:
        conds.append(Payment.created_at >= f.created_from)
    if f.created_to:
        conds.append(Payment.created_at < f.created_to)
    if f.q:
        term = f.q.strip()
        conds.append(or_(Payment.id == term, Payment.merchant_reference == term, Payment.order_reference == term))
    total = db.scalar(select(func.count()).select_from(Payment).where(*conds)) or 0
    stmt = select(Payment, Merchant.business_name) if with_merchant else select(Payment)
    if with_merchant:
        stmt = stmt.join(Merchant, Merchant.id == Payment.merchant_id)
    stmt = stmt.where(*conds).order_by(Payment.created_at.desc(), Payment.id).offset((page - 1) * page_size).limit(page_size)
    rows = db.execute(stmt).all() if with_merchant else db.scalars(stmt).all()
    return rows, total
