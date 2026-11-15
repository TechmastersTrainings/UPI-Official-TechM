from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import MerchantContext, request_meta, require_merchant
from app.api.auth.routes import _require_client_header
from app.db.session import get_db
from app.models import ApiRequestLog
from app.schemas.admin import Page
from app.schemas.merchant import (
    ApiAccessToggle,
    ApiRequestLogOut,
    BankAccountCreate,
    BankAccountOut,
    BankAccountUpdate,
    CredentialCreate,
    CredentialOut,
    CredentialWithSecret,
    Env,
    LiveReadiness,
    MerchantOut,
    MerchantProfileUpdate,
    MerchantRegistrationRequest,
    ProviderConfigCreate,
    ProviderConfigOut,
    ProviderConfigUpdate,
    ProviderOut,
    RevealedAccountNumber,
    WebhookConfigOut,
    WebhookConfigUpsert,
    WebhookConfigWithSecret,
)
from app.services import bank_accounts, credentials, merchants, provider_configs, webhook_configs
from app.services.rbac import Perm

router = APIRouter(prefix="/api/merchant", tags=["Merchant console"])


# ---------- Registration (public) ----------
@router.post("/register", response_model=MerchantOut, status_code=201)
def register(body: MerchantRegistrationRequest, request: Request, db: Session = Depends(get_db)):
    """Self-service merchant registration. Creates the merchant (PENDING_REVIEW), its business profile,
    the owner login (MERCHANT_ADMIN) and the TEST-only sandbox configuration. Live collection stays
    unavailable until TechMasters approval and provider onboarding are complete."""
    _require_client_header(request)
    merchant, _ = merchants.register(db, body, request_meta(request))
    return MerchantOut.model_validate(merchant)


# ---------- Profile ----------
@router.get("/profile", response_model=MerchantOut)
def get_profile(ctx: MerchantContext = Depends(require_merchant(Perm.M_VIEW))):
    return MerchantOut.model_validate(ctx.merchant)


@router.patch("/profile", response_model=MerchantOut)
def update_profile(
    body: MerchantProfileUpdate, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_PROFILE_EDIT, write=True)), db: Session = Depends(get_db),
):
    return MerchantOut.model_validate(merchants.update_profile(db, ctx.merchant, body, ctx.user, request_meta(request)))


@router.get("/live-readiness", response_model=LiveReadiness)
def live_readiness(ctx: MerchantContext = Depends(require_merchant(Perm.M_VIEW)), db: Session = Depends(get_db)):
    return merchants.live_readiness(db, ctx.merchant)


# ---------- Bank accounts ----------
@router.get("/bank-accounts", response_model=list[BankAccountOut])
def list_bank_accounts(
    environment: Env | None = None,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_BANK_VIEW)), db: Session = Depends(get_db),
):
    return [bank_accounts.to_out(a) for a in bank_accounts.list_for(db, ctx.merchant.id, environment)]


@router.post("/bank-accounts", response_model=BankAccountOut, status_code=201)
def create_bank_account(
    body: BankAccountCreate, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_BANK_MANAGE, write=True)), db: Session = Depends(get_db),
):
    return bank_accounts.to_out(bank_accounts.create(db, ctx.merchant.id, body, ctx.user, request_meta(request)))


@router.patch("/bank-accounts/{account_id}", response_model=BankAccountOut)
def update_bank_account(
    account_id: str, body: BankAccountUpdate, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_BANK_MANAGE, write=True)), db: Session = Depends(get_db),
):
    acct = bank_accounts.get_owned(db, ctx.merchant.id, account_id)
    return bank_accounts.to_out(bank_accounts.update_account(db, acct, body, ctx.user, request_meta(request)))


@router.post("/bank-accounts/{account_id}/default", response_model=BankAccountOut)
def set_default_bank_account(
    account_id: str, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_BANK_MANAGE, write=True)), db: Session = Depends(get_db),
):
    acct = bank_accounts.get_owned(db, ctx.merchant.id, account_id)
    return bank_accounts.to_out(bank_accounts.set_default(db, acct, ctx.user, request_meta(request)))


@router.post("/bank-accounts/{account_id}/activate", response_model=BankAccountOut)
def activate_bank_account(
    account_id: str, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_BANK_MANAGE, write=True)), db: Session = Depends(get_db),
):
    acct = bank_accounts.get_owned(db, ctx.merchant.id, account_id)
    return bank_accounts.to_out(bank_accounts.set_active(db, acct, True, ctx.user, request_meta(request)))


@router.post("/bank-accounts/{account_id}/deactivate", response_model=BankAccountOut)
def deactivate_bank_account(
    account_id: str, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_BANK_MANAGE, write=True)), db: Session = Depends(get_db),
):
    acct = bank_accounts.get_owned(db, ctx.merchant.id, account_id)
    return bank_accounts.to_out(bank_accounts.set_active(db, acct, False, ctx.user, request_meta(request)))


@router.post("/bank-accounts/{account_id}/reveal", response_model=RevealedAccountNumber)
def reveal_bank_account(
    account_id: str, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_BANK_REVEAL)), db: Session = Depends(get_db),
):
    acct = bank_accounts.get_owned(db, ctx.merchant.id, account_id)
    return RevealedAccountNumber(id=acct.id, account_number=bank_accounts.reveal(db, acct, ctx.user, request_meta(request)))


# ---------- Payment providers ----------
@router.get("/providers", response_model=list[ProviderOut])
def list_providers(_: MerchantContext = Depends(require_merchant(Perm.M_VIEW)), db: Session = Depends(get_db)):
    return [ProviderOut.model_validate(p) for p in provider_configs.list_providers(db) if p.is_enabled]


@router.get("/provider-configs", response_model=list[ProviderConfigOut])
def list_provider_configs(ctx: MerchantContext = Depends(require_merchant(Perm.M_VIEW)), db: Session = Depends(get_db)):
    return [provider_configs.to_out(c) for c in provider_configs.list_for(db, ctx.merchant.id)]


@router.post("/provider-configs", response_model=ProviderConfigOut, status_code=201)
def create_provider_config(
    body: ProviderConfigCreate, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_PROVIDERS_MANAGE, write=True)), db: Session = Depends(get_db),
):
    return provider_configs.to_out(provider_configs.create(db, ctx.merchant.id, body, ctx.user, request_meta(request)))


@router.patch("/provider-configs/{config_id}", response_model=ProviderConfigOut)
def update_provider_config(
    config_id: str, body: ProviderConfigUpdate, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_PROVIDERS_MANAGE, write=True)), db: Session = Depends(get_db),
):
    cfg = provider_configs.get_owned(db, ctx.merchant.id, config_id)
    return provider_configs.to_out(provider_configs.update(db, cfg, body, ctx.user, request_meta(request)))


@router.post("/provider-configs/{config_id}/submit", response_model=ProviderConfigOut)
def submit_provider_config(
    config_id: str, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_PROVIDERS_MANAGE, write=True)), db: Session = Depends(get_db),
):
    cfg = provider_configs.get_owned(db, ctx.merchant.id, config_id)
    return provider_configs.to_out(provider_configs.submit(db, cfg, ctx.user, request_meta(request)))


# ---------- API credentials ----------
@router.get("/api-credentials", response_model=list[CredentialOut])
def list_credentials(ctx: MerchantContext = Depends(require_merchant(Perm.M_KEYS_MANAGE)), db: Session = Depends(get_db)):
    return [CredentialOut.model_validate(c) for c in credentials.list_for(db, ctx.merchant.id)]


@router.post("/api-credentials", response_model=CredentialWithSecret, status_code=201)
def generate_credential(
    body: CredentialCreate, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_KEYS_MANAGE, write=True)), db: Session = Depends(get_db),
):
    cred, secret = credentials.generate(db, ctx.merchant, body.environment, body.label, ctx.user, request_meta(request))
    return CredentialWithSecret(**CredentialOut.model_validate(cred).model_dump(), key_secret=secret)


@router.post("/api-credentials/{credential_id}/regenerate", response_model=CredentialWithSecret, status_code=201)
def regenerate_credential(
    credential_id: str, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_KEYS_MANAGE, write=True)), db: Session = Depends(get_db),
):
    cred = credentials.get_owned(db, ctx.merchant.id, credential_id)
    new, secret = credentials.regenerate(db, ctx.merchant, cred, ctx.user, request_meta(request))
    return CredentialWithSecret(**CredentialOut.model_validate(new).model_dump(), key_secret=secret)


@router.post("/api-credentials/{credential_id}/revoke", response_model=CredentialOut)
def revoke_credential(
    credential_id: str, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_KEYS_MANAGE)), db: Session = Depends(get_db),
):
    # Revocation is allowed even when suspended: removing access must always be possible.
    cred = credentials.get_owned(db, ctx.merchant.id, credential_id)
    return CredentialOut.model_validate(credentials.revoke(db, cred, ctx.user, request_meta(request)))


@router.put("/api-access", response_model=MerchantOut)
def set_api_access(
    body: ApiAccessToggle, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_KEYS_MANAGE, write=True)), db: Session = Depends(get_db),
):
    return MerchantOut.model_validate(merchants.set_api_access(db, ctx.merchant, body.enabled, ctx.user, request_meta(request)))


@router.get("/api-request-logs", response_model=Page[ApiRequestLogOut])
def api_request_logs(
    environment: Env | None = None,
    status_code: int | None = Query(None, ge=100, le=599),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    ctx: MerchantContext = Depends(require_merchant(Perm.M_LOGS_VIEW)), db: Session = Depends(get_db),
):
    conds = [ApiRequestLog.merchant_id == ctx.merchant.id]
    if environment:
        conds.append(ApiRequestLog.environment == environment)
    if status_code:
        conds.append(ApiRequestLog.status_code == status_code)
    total = db.scalar(select(func.count()).select_from(ApiRequestLog).where(*conds)) or 0
    rows = db.scalars(select(ApiRequestLog).where(*conds).order_by(ApiRequestLog.created_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[ApiRequestLogOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


# ---------- Webhooks ----------
@router.get("/webhooks", response_model=list[WebhookConfigOut])
def list_webhooks(ctx: MerchantContext = Depends(require_merchant(Perm.M_WEBHOOKS_MANAGE)), db: Session = Depends(get_db)):
    return [WebhookConfigOut.model_validate(w) for w in webhook_configs.list_for(db, ctx.merchant.id)]


@router.put("/webhooks/{environment}", response_model=WebhookConfigWithSecret | WebhookConfigOut)
def upsert_webhook(
    environment: Env, body: WebhookConfigUpsert, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_WEBHOOKS_MANAGE, write=True)), db: Session = Depends(get_db),
):
    """Create or update the webhook endpoint for an environment. The signing secret is included in the
    response only when the configuration is first created."""
    cfg, secret = webhook_configs.upsert(db, ctx.merchant.id, environment, body, ctx.user, request_meta(request))
    out = WebhookConfigOut.model_validate(cfg)
    return WebhookConfigWithSecret(**out.model_dump(), signing_secret=secret) if secret else out


@router.post("/webhooks/{environment}/rotate-secret", response_model=WebhookConfigWithSecret)
def rotate_webhook_secret(
    environment: Env, request: Request,
    ctx: MerchantContext = Depends(require_merchant(Perm.M_WEBHOOKS_MANAGE, write=True)), db: Session = Depends(get_db),
):
    cfg, secret = webhook_configs.rotate_secret(db, ctx.merchant.id, environment, ctx.user, request_meta(request))
    return WebhookConfigWithSecret(**WebhookConfigOut.model_validate(cfg).model_dump(), signing_secret=secret)
