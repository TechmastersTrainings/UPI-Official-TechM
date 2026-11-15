from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, request_meta, require
from app.core.errors import NotFound
from app.db.session import get_db
from app.models import PaymentProvider
from app.schemas.admin import Page
from app.schemas.merchant import (
    BankAccountOut,
    BankVerificationDecision,
    CredentialOut,
    LiveReadiness,
    MerchantOut,
    MerchantSummaryOut,
    MerchantUserOut,
    ProviderConfigOut,
    ProviderOut,
    ReasonRequired,
    RevealedAccountNumber,
    StatusChange,
    WebhookConfigOut,
)
from app.services import bank_accounts, credentials, merchants, provider_configs, webhook_configs
from app.services.rbac import Perm

router = APIRouter(prefix="/api/admin", tags=["Super Admin — merchants"])

StatusFilter = Literal["PENDING_REVIEW", "ACTIVE", "SUSPENDED", "REJECTED"]


@router.get("/merchants", response_model=Page[MerchantSummaryOut])
def list_merchants(
    q: str | None = Query(None, max_length=200, description="Name, email prefix or merchant ID"),
    status: StatusFilter | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    _: CurrentUser = Depends(require(Perm.MERCHANTS_VIEW)),
    db: Session = Depends(get_db),
):
    rows, total = merchants.search(db, q=q, status=status, page=page, page_size=page_size)
    return Page(items=[MerchantSummaryOut.model_validate(m, from_attributes=True) for m in rows],
                total=total, page=page, page_size=page_size)


@router.get("/merchants/{merchant_id}")
def merchant_detail(merchant_id: str, _: CurrentUser = Depends(require(Perm.MERCHANTS_VIEW)), db: Session = Depends(get_db)):
    m = merchants.get(db, merchant_id)
    return {
        "merchant": MerchantOut.model_validate(m),
        "live_readiness": LiveReadiness(**merchants.live_readiness(db, m)),
        "users": [
            MerchantUserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role.name, is_active=u.is_active,
                            last_login_at=u.last_login_at)
            for u in merchants.merchant_users(db, m.id)
        ],
        "bank_accounts": [bank_accounts.to_out(a) for a in bank_accounts.list_for(db, m.id)],
        "provider_configs": [provider_configs.to_out(c) for c in provider_configs.list_for(db, m.id)],
        "api_credentials": [CredentialOut.model_validate(c) for c in credentials.list_for(db, m.id)],
        "webhooks": [WebhookConfigOut.model_validate(w) for w in webhook_configs.list_for(db, m.id)],
    }


def _status_route(action: str, needs_reason: bool):
    body_model = ReasonRequired if needs_reason else StatusChange

    def handler(
        merchant_id: str, body: body_model, request: Request,  # type: ignore[valid-type]
        current: CurrentUser = Depends(require(Perm.MERCHANTS_MANAGE)), db: Session = Depends(get_db),
    ) -> MerchantOut:
        m = merchants.get(db, merchant_id)
        return MerchantOut.model_validate(
            merchants.change_status(db, m, action, body.reason, current.user, request_meta(request))
        )

    handler.__name__ = f"merchant_{action}"
    router.add_api_route(f"/merchants/{{merchant_id}}/{action}", handler, methods=["POST"], response_model=MerchantOut,
                         summary=f"{action.capitalize()} merchant")


for _action, _reason in (("approve", False), ("reject", True), ("suspend", True), ("reactivate", False), ("reopen", False)):
    _status_route(_action, _reason)


@router.post("/merchants/{merchant_id}/live/enable", response_model=MerchantOut)
def enable_live(merchant_id: str, request: Request, current: CurrentUser = Depends(require(Perm.MERCHANTS_LIVE)),
                db: Session = Depends(get_db)):
    """Turns on live payment collection. Refused with `LIVE_PREREQUISITES_UNMET` (and the unmet items)
    unless every readiness item is satisfied."""
    m = merchants.get(db, merchant_id)
    return MerchantOut.model_validate(merchants.set_live(db, m, True, current.user, request_meta(request)))


@router.post("/merchants/{merchant_id}/live/disable", response_model=MerchantOut)
def disable_live(merchant_id: str, request: Request, current: CurrentUser = Depends(require(Perm.MERCHANTS_LIVE)),
                 db: Session = Depends(get_db)):
    m = merchants.get(db, merchant_id)
    return MerchantOut.model_validate(merchants.set_live(db, m, False, current.user, request_meta(request)))


@router.post("/merchants/{merchant_id}/api-access/{state}", response_model=MerchantOut)
def admin_api_access(merchant_id: str, state: Literal["enable", "disable"], request: Request,
                     current: CurrentUser = Depends(require(Perm.MERCHANTS_MANAGE)), db: Session = Depends(get_db)):
    m = merchants.get(db, merchant_id)
    return MerchantOut.model_validate(merchants.set_api_access(db, m, state == "enable", current.user, request_meta(request)))


# ---------- Bank account verification ----------
@router.post("/bank-accounts/{account_id}/verification", response_model=BankAccountOut)
def decide_bank_verification(account_id: str, body: BankVerificationDecision, request: Request,
                             current: CurrentUser = Depends(require(Perm.MERCHANTS_MANAGE)), db: Session = Depends(get_db)):
    acct = bank_accounts.get_owned(db, None, account_id)
    return bank_accounts.to_out(
        bank_accounts.decide_verification(db, acct, body.decision, body.note, current.user, request_meta(request))
    )


@router.post("/bank-accounts/{account_id}/reveal", response_model=RevealedAccountNumber)
def admin_reveal_bank_account(account_id: str, request: Request,
                              current: CurrentUser = Depends(require(Perm.SENSITIVE_REVEAL)), db: Session = Depends(get_db)):
    acct = bank_accounts.get_owned(db, None, account_id)
    return RevealedAccountNumber(id=acct.id, account_number=bank_accounts.reveal(db, acct, current.user, request_meta(request)))


# ---------- Provider onboarding ----------
def _cfg(db, config_id):
    return provider_configs.get_owned(db, None, config_id)


@router.post("/provider-configs/{config_id}/approve", response_model=ProviderConfigOut)
def approve_provider_config(config_id: str, request: Request,
                            current: CurrentUser = Depends(require(Perm.MERCHANTS_MANAGE)), db: Session = Depends(get_db)):
    """Confirms that the payment provider has completed onboarding/KYC for this merchant."""
    return provider_configs.to_out(provider_configs.approve(db, _cfg(db, config_id), current.user, request_meta(request)))


@router.post("/provider-configs/{config_id}/reject", response_model=ProviderConfigOut)
def reject_provider_config(config_id: str, body: ReasonRequired, request: Request,
                           current: CurrentUser = Depends(require(Perm.MERCHANTS_MANAGE)), db: Session = Depends(get_db)):
    return provider_configs.to_out(
        provider_configs.reject(db, _cfg(db, config_id), body.reason, current.user, request_meta(request))
    )


@router.post("/provider-configs/{config_id}/activate", response_model=ProviderConfigOut)
def activate_provider_config(config_id: str, request: Request,
                             current: CurrentUser = Depends(require(Perm.MERCHANTS_LIVE)), db: Session = Depends(get_db)):
    return provider_configs.to_out(provider_configs.activate(db, _cfg(db, config_id), current.user, request_meta(request)))


@router.post("/provider-configs/{config_id}/disable", response_model=ProviderConfigOut)
def disable_provider_config(config_id: str, body: ReasonRequired, request: Request,
                            current: CurrentUser = Depends(require(Perm.MERCHANTS_MANAGE)), db: Session = Depends(get_db)):
    return provider_configs.to_out(
        provider_configs.disable(db, _cfg(db, config_id), body.reason, current.user, request_meta(request))
    )


@router.get("/providers", response_model=list[ProviderOut])
def list_providers(_: CurrentUser = Depends(require(Perm.MERCHANTS_VIEW)), db: Session = Depends(get_db)):
    return [ProviderOut.model_validate(p) for p in provider_configs.list_providers(db)]


@router.post("/providers/{provider_id}/{state}", response_model=ProviderOut)
def toggle_provider(provider_id: str, state: Literal["enable", "disable"], request: Request,
                    current: CurrentUser = Depends(require(Perm.MERCHANTS_LIVE)), db: Session = Depends(get_db)):
    provider = db.get(PaymentProvider, provider_id)
    if provider is None:
        raise NotFound("Provider not found")
    return ProviderOut.model_validate(
        provider_configs.set_provider_enabled(db, provider, state == "enable", current.user, request_meta(request))
    )

