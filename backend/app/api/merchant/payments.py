from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import MerchantContext, request_meta, require_merchant
from app.db.session import get_db
from app.models.enums import ActorType, EventSource, PaymentStatus
from app.schemas.admin import Page
from app.schemas.merchant import Env
from app.schemas.payment import PaymentCancel, PaymentDetail, PaymentEventOut, PaymentListItem, PaymentOut
from app.services import audit, payments
from app.services.rbac import Perm

router = APIRouter(prefix="/api/merchant/payments", tags=["Merchant console"])
StatusLiteral = Literal[tuple(s.value for s in PaymentStatus)]  # type: ignore[valid-type]


def detail(db: Session, p, merchant_name: str | None = None) -> PaymentDetail:
    base = PaymentOut.of(p).model_dump()
    return PaymentDetail(
        **base, merchant_id=p.merchant_id, merchant_name=merchant_name, provider_code=p.provider_code,
        events=[PaymentEventOut.model_validate(e) for e in payments.events(db, p.id)],
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
