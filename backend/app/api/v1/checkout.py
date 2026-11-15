"""Public hosted-checkout endpoints, used by the customer's browser. Authenticated only by the
unguessable checkout token in the link (256-bit). They expose no PII or secrets and never accept
a status from the client: the page shows whatever the server says."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import NotFound
from app.db.session import get_db
from app.db.types import utcnow
from app.models import Merchant, Payment
from app.models.enums import EventSource, PaymentStatus
from app.schemas.payment import CheckoutView, SessionOut
from app.services import checkout

router = APIRouter(prefix="/api/v1/checkout", tags=["Hosted checkout (public)"])

FINAL = {PaymentStatus.SUCCESS, PaymentStatus.FAILED, PaymentStatus.EXPIRED, PaymentStatus.CANCELLED,
         PaymentStatus.REFUND_PENDING, PaymentStatus.PARTIALLY_REFUNDED, PaymentStatus.REFUNDED}


def _limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    rate_limit.hit(f"checkout:{ip}", get_settings().CHECKOUT_RATE_LIMIT_PER_MINUTE)


def _load(db: Session, token: str) -> Payment:
    p = checkout.by_token(db, token)
    if p is None:
        raise NotFound("This payment link is not valid", code="CHECKOUT_NOT_FOUND")
    return checkout.sync_expiry(db, p)


def _view(db: Session, p: Payment, attempt=None) -> CheckoutView:
    merchant = db.get(Merchant, p.merchant_id)
    if attempt is None and p.status in checkout.AWAITING_STATUSES:
        attempt = checkout.latest_attempt(db, p.id)
    awaiting = p.status in checkout.AWAITING_STATUSES and attempt is not None
    return CheckoutView(
        payment_id=p.id, merchant_name=merchant.business_name, reference=p.order_reference or p.merchant_reference,
        amount=p.amount, currency=p.currency, status=p.status, environment=p.environment,
        payment_method=p.payment_method, expires_at=p.expires_at, server_time=utcnow(),
        session=SessionOut.of(attempt) if awaiting else None,
        return_url=p.return_url if p.status in FINAL else None,
    )


@router.get("/{token}", response_model=CheckoutView, dependencies=[Depends(_limit)])
def get_checkout(token: str, db: Session = Depends(get_db)):
    return _view(db, _load(db, token))


@router.post("/{token}/initiate", response_model=CheckoutView, dependencies=[Depends(_limit)])
def initiate_checkout(token: str, db: Session = Depends(get_db)):
    """Customer chose to pay: open (or reuse) the provider session and return the QR / intent."""
    p = _load(db, token)
    attempt = checkout.open_session(db, p, source=EventSource.CHECKOUT)
    db.refresh(p)
    return _view(db, p, attempt)
