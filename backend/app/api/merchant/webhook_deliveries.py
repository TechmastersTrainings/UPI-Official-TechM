from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import MerchantContext, request_meta, require_merchant
from app.core.errors import NotFound
from app.db.session import get_db
from app.models import WebhookDelivery
from app.models.enums import WebhookDeliveryStatus
from app.schemas.admin import Page
from app.schemas.merchant import Env
from app.schemas.payment import WebhookDeliveryDetail, WebhookDeliveryOut
from app.services import audit, webhooks
from app.services.rbac import Perm

router = APIRouter(prefix="/api/merchant/webhook-deliveries", tags=["Merchant console"])
DeliveryStatus = Literal[tuple(s.value for s in WebhookDeliveryStatus)]  # type: ignore[valid-type]


def _owned(db: Session, merchant_id: str, delivery_id: str) -> WebhookDelivery:
    d = db.get(WebhookDelivery, delivery_id)
    if d is None or d.merchant_id != merchant_id:
        raise NotFound("Delivery not found")
    return d


@router.get("", response_model=Page[WebhookDeliveryOut])
def list_deliveries(
    environment: Env | None = None,
    status: DeliveryStatus | None = None,
    payment_id: str | None = Query(None, max_length=32),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    ctx: MerchantContext = Depends(require_merchant(Perm.M_WEBHOOKS_MANAGE)),
    db: Session = Depends(get_db),
):
    rows, total = webhooks.list_for(db, ctx.merchant.id, environment, payment_id, status, page, page_size)
    return Page(items=[WebhookDeliveryOut.model_validate(d) for d in rows], total=total, page=page, page_size=page_size)


@router.get("/{delivery_id}", response_model=WebhookDeliveryDetail)
def get_delivery(delivery_id: str, ctx: MerchantContext = Depends(require_merchant(Perm.M_WEBHOOKS_MANAGE)),
                 db: Session = Depends(get_db)):
    return WebhookDeliveryDetail.model_validate(_owned(db, ctx.merchant.id, delivery_id))


@router.post("/{delivery_id}/redeliver", response_model=WebhookDeliveryOut)
def redeliver(delivery_id: str, request: Request,
              ctx: MerchantContext = Depends(require_merchant(Perm.M_WEBHOOKS_MANAGE, write=True)),
              db: Session = Depends(get_db)):
    d = webhooks.redeliver(db, _owned(db, ctx.merchant.id, delivery_id))
    audit.record(db, "webhook.redelivered", actor=ctx.user, entity_type="webhook_delivery", entity_id=d.id,
                 merchant_id=ctx.merchant.id, details={"event_id": d.event_id, "result": d.status}, meta=request_meta(request))
    db.commit()
    return WebhookDeliveryOut.model_validate(d)


@router.post("/test/{environment}", response_model=WebhookDeliveryOut)
def send_test(environment: Env, request: Request,
              ctx: MerchantContext = Depends(require_merchant(Perm.M_WEBHOOKS_MANAGE, write=True)),
              db: Session = Depends(get_db)):
    """Send a signed `webhook.test` event now. A 2xx response validates the endpoint."""
    d = webhooks.send_test(db, ctx.merchant.id, environment)
    audit.record(db, "webhook.test_sent", actor=ctx.user, entity_type="webhook_delivery", entity_id=d.id,
                 merchant_id=ctx.merchant.id, details={"environment": environment, "result": d.status,
                                                       "response_code": d.last_response_code}, meta=request_meta(request))
    db.commit()
    return WebhookDeliveryOut.model_validate(d)
