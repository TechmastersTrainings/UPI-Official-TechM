from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import ApiClient, get_api_client, idempotency_key
from app.db.session import get_db
from app.models.enums import EventSource, PaymentStatus
from app.schemas.admin import Page
from app.schemas.payment import (
    PaymentCancel,
    PaymentCreate,
    PaymentListItem,
    PaymentOut,
    PaymentSession,
    PaymentStatusOut,
    SessionOut,
)
from app.services import checkout, payments

router = APIRouter(prefix="/api/v1", tags=["Gateway API"])

StatusLiteral = Literal[tuple(s.value for s in PaymentStatus)]  # type: ignore[valid-type]


@router.post(
    "/payments/create",
    response_model=PaymentOut,
    status_code=201,
    responses={200: {"description": "Replay of an earlier request with the same Idempotency-Key and body"}},
)
def create_payment(
    body: PaymentCreate,
    response: Response,
    client: ApiClient = Depends(get_api_client),
    key: str = Depends(idempotency_key),
    db: Session = Depends(get_db),
):
    """Create a payment order. Requires an `Idempotency-Key` header: retrying with the same key and
    body returns the original payment (`Idempotent-Replayed: true`); the same key with a different
    body is rejected with `409 IDEMPOTENCY_CONFLICT`.

    The payment starts as `CREATED`. Its status only changes on the gateway's side, from verified
    provider data. Never treat a customer redirect to your `return_url` as proof of payment: check
    the status with `GET /api/v1/payments/{id}` (or wait for the webhook) before fulfilling an order."""
    result = payments.create(db, client.credential, client.merchant, body, key)
    if result.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return PaymentOut.of(result.payment)


@router.get("/payments", response_model=Page[PaymentListItem])
def list_payments(
    status: StatusLiteral | None = None,
    merchant_reference: str | None = Query(None, max_length=100),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    client: ApiClient = Depends(get_api_client),
    db: Session = Depends(get_db),
):
    """Payments in the API key's environment, newest first."""
    rows, total = payments.search(db, payments.PaymentFilter(
        merchant_id=client.merchant.id, environment=client.environment, status=status, q=merchant_reference,
        created_from=created_from, created_to=created_to,
    ), page, page_size)
    return Page(items=[PaymentListItem.model_validate(p) for p in rows], total=total, page=page, page_size=page_size)


@router.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: str, client: ApiClient = Depends(get_api_client), db: Session = Depends(get_db)):
    return PaymentOut.of(payments.get_scoped(db, client.merchant.id, client.environment, payment_id))


@router.get("/payments/{payment_id}/status", response_model=PaymentStatusOut)
def get_payment_status(payment_id: str, client: ApiClient = Depends(get_api_client), db: Session = Depends(get_db)):
    """Lightweight status check, suitable for polling."""
    return PaymentStatusOut.model_validate(payments.get_scoped(db, client.merchant.id, client.environment, payment_id))


@router.post("/payments/{payment_id}/cancel", response_model=PaymentOut)
def cancel_payment(
    payment_id: str,
    body: PaymentCancel | None = None,
    client: ApiClient = Depends(get_api_client),
    db: Session = Depends(get_db),
):
    """Cancel a payment the customer has not started paying (status `CREATED`). Safe to retry."""
    p = payments.get_scoped(db, client.merchant.id, client.environment, payment_id)
    p = payments.cancel(db, p, source=EventSource.MERCHANT_API, reason=body.reason if body else None,
                        actor=client.credential.key_id)
    return PaymentOut.of(p)


@router.post("/payments/{payment_id}/initiate", response_model=PaymentSession)
def initiate_payment(payment_id: str, client: ApiClient = Depends(get_api_client), db: Session = Depends(get_db)):
    """Open a provider session and get the UPI QR content / intent link to show your customer
    (for `UPI_QR` / `UPI_INTENT` integrations that render their own payment screen). Safe to retry:
    if a session is already open it is returned. Use `checkout_url` instead to let TechMasters host
    the payment page."""
    p = payments.get_scoped(db, client.merchant.id, client.environment, payment_id)
    attempt = checkout.open_session(db, p, source=EventSource.MERCHANT_API)
    db.refresh(p)
    return PaymentSession(payment=PaymentOut.of(p), session=SessionOut.of(attempt))
