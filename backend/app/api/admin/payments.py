from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require
from app.api.merchant.payments import detail
from app.core.errors import NotFound
from app.db.session import get_db
from app.models import Merchant, Payment
from app.models.enums import PaymentStatus
from app.schemas.admin import Page
from app.schemas.merchant import Env
from app.schemas.payment import AdminPaymentListItem, PaymentDetail, PaymentListItem
from app.services import payments
from app.services.rbac import Perm

router = APIRouter(prefix="/api/admin/payments", tags=["Super Admin"])
StatusLiteral = Literal[tuple(s.value for s in PaymentStatus)]  # type: ignore[valid-type]


@router.get("", response_model=Page[AdminPaymentListItem])
def list_payments(
    environment: Env = "LIVE",
    merchant_id: str | None = Query(None, max_length=32),
    status: StatusLiteral | None = None,
    q: str | None = Query(None, max_length=100),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    _: CurrentUser = Depends(require(Perm.PAYMENTS_VIEW)),
    db: Session = Depends(get_db),
):
    rows, total = payments.search(db, payments.PaymentFilter(
        merchant_id=merchant_id, environment=environment, status=status, q=q,
        created_from=created_from, created_to=created_to,
    ), page, page_size, with_merchant=True)
    items = [
        AdminPaymentListItem(**PaymentListItem.model_validate(p).model_dump(), merchant_name=name) for p, name in rows
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{payment_id}", response_model=PaymentDetail)
def get_payment(payment_id: str, _: CurrentUser = Depends(require(Perm.PAYMENTS_VIEW)), db: Session = Depends(get_db)):
    p = db.get(Payment, payment_id)
    if p is None:
        raise NotFound("Payment not found", code="PAYMENT_NOT_FOUND")
    p = payments.expire_if_due(db, p)
    merchant = db.get(Merchant, p.merchant_id)
    return detail(db, p, merchant.business_name if merchant else None)
