from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import MerchantContext, request_meta, require_merchant
from app.db.session import get_db
from app.models.enums import ActorType, EventSource, PaymentStatus
from app.schemas.admin import Page
from app.schemas.merchant import Env
from app.schemas.payment import (
    AttemptOut,
    PaymentCancel,
    PaymentDetail,
    PaymentEventOut,
    PaymentListItem,
    PaymentOut,
    ConsoleRefundCreate,
    RefundCreate,
    RefundOut,
    TransactionOut,
    WebhookDeliveryOut,
)
from sqlalchemy import select

from app.models import Transaction, WebhookDelivery
from app.api.v1.deps import idempotency_key
from app.services import audit, checkout, payments, refunds
from app.services.rbac import Perm

router = APIRouter(prefix="/api/merchant/payments", tags=["Merchant console"])
StatusLiteral = Literal[tuple(s.value for s in PaymentStatus)]  # type: ignore[valid-type]


def detail(db: Session, p, merchant_name: str | None = None) -> PaymentDetail:
    base = PaymentOut.of(p).model_dump()
    return PaymentDetail(
        **base, merchant_id=p.merchant_id, merchant_name=merchant_name, provider_code=p.provider_code,
        attempts=[AttemptOut.model_validate(a) for a in checkout.attempts(db, p.id)],
        events=[PaymentEventOut.model_validate(e) for e in payments.events(db, p.id)],
        transactions=[TransactionOut.model_validate(t) for t in db.scalars(
            select(Transaction).where(Transaction.payment_id == p.id).order_by(Transaction.verified_at))],
        refunds=[RefundOut.model_validate(r) for r in refunds.for_payment(db, p.id)],
        webhook_deliveries=[WebhookDeliveryOut.model_validate(d) for d in db.scalars(
            select(WebhookDelivery).where(WebhookDelivery.payment_id == p.id).order_by(WebhookDelivery.created_at))],
    )


@router.get("", response_model=Page[PaymentListItem])
def list_payments(
    environment: Env = "TEST",
    status: StatusLiteral | None = None,
    q: str | None = Query(None, max_length=100, description="Payment id, merchant reference or order reference"),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    ctx: MerchantContext = Depends(require_merchant(Perm.M_PAYMENTS_VIEW)),
    db: Session = Depends(get_db),
):
    rows, total = payments.search(db, payments.PaymentFilter(
        merchant_id=ctx.merchant.id, environment=environment, status=status, q=q,
        created_from=created_from, created_to=created_to,
    ), page, page_size)
    return Page(items=[PaymentListItem.model_validate(p) for p in rows], total=total, page=page, page_size=page_size)


@router.get("/{payment_id}", response_model=PaymentDetail)
def get_payment(
    payment_id: str,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_PAYMENTS_VIEW)),
    db: Session = Depends(get_db),
):
    return detail(db, payments.get_scoped(db, ctx.merchant.id, None, payment_id))


@router.post("/{payment_id}/cancel", response_model=PaymentDetail)
def cancel_payment(
    payment_id: str,
    request: Request,
    body: PaymentCancel | None = None,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_PAYMENTS_MANAGE, write=True)),
    db: Session = Depends(get_db),
):
    p = payments.get_scoped(db, ctx.merchant.id, None, payment_id)
    was = p.status
    reason = body.reason if body else None
    p = payments.cancel(db, p, source=EventSource.MERCHANT_API, reason=reason, actor=ctx.user.email)
    if was != p.status:
        audit.record(db, "payment.cancelled", actor=ctx.user, actor_type=ActorType.USER, entity_type="payment",
                     entity_id=p.id, merchant_id=p.merchant_id, details={"reason": reason}, meta=request_meta(request))
        db.commit()
    return detail(db, p)


@router.post("/{payment_id}/refunds", response_model=PaymentDetail, status_code=201)
def refund_payment(
    payment_id: str,
    body: ConsoleRefundCreate,
    request: Request,
    key: str = Depends(idempotency_key),
    ctx: MerchantContext = Depends(require_merchant(Perm.M_PAYMENTS_MANAGE, write=True)),
    db: Session = Depends(get_db),
):
    """Refund from the console (same rules as `POST /api/v1/refunds`)."""
    p = payments.get_scoped(db, ctx.merchant.id, None, payment_id)
    refund, replayed = refunds.create(
        db, ctx.merchant, p.environment, RefundCreate(payment_id=p.id, amount=body.amount, reason=body.reason), key,
        source=EventSource.MERCHANT_API, user_id=ctx.user.id,
    )
    if not replayed:
        audit.record(db, "refund.created", actor=ctx.user, actor_type=ActorType.USER, entity_type="refund",
                     entity_id=refund.id, merchant_id=p.merchant_id,
                     details={"payment_id": p.id, "amount": refund.amount, "status": refund.status},
                     meta=request_meta(request))
        db.commit()
    db.refresh(p)
    return detail(db, p)
