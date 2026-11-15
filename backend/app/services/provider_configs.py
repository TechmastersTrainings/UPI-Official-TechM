"""Merchant ↔ payment-provider onboarding records.

Lifecycle: DRAFT → SUBMITTED (merchant) → APPROVED (TechMasters confirms the provider has onboarded
the merchant) → TESTED (automated provider integration test, Phase 7) → ACTIVE (TechMasters).
A rejection returns the config to DRAFT with a reason. DISABLED can be set at any time.
Credentials are encrypted at rest and never returned; only their field names are exposed."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_json, encrypt_json
from app.core.errors import AppError, Conflict, NotFound
from app.db.types import utcnow
from app.models import PaymentProvider, ProviderConfiguration, User
from app.models.enums import Environment, ProviderConfigStatus as S
from app.schemas.merchant import ProviderConfigCreate, ProviderConfigOut, ProviderConfigUpdate, ProviderOut
from app.services import audit
from app.services.audit import RequestMeta

SANDBOX = "sandbox"


def to_out(c: ProviderConfiguration) -> ProviderConfigOut:
    fields = sorted(decrypt_json(c.credentials_enc).keys()) if c.credentials_enc else []
    return ProviderConfigOut(
        id=c.id, merchant_id=c.merchant_id, provider=ProviderOut.model_validate(c.provider), environment=c.environment,
        provider_merchant_id=c.provider_merchant_id, credential_fields=fields, status=c.status,
        status_reason=c.status_reason, submitted_at=c.submitted_at, approved_at=c.approved_at,
        integration_tested_at=c.integration_tested_at, created_at=c.created_at, updated_at=c.updated_at,
    )


def list_providers(db: Session) -> list[PaymentProvider]:
    return list(db.scalars(select(PaymentProvider).order_by(PaymentProvider.name)))


def list_for(db: Session, merchant_id: str) -> list[ProviderConfiguration]:
    return list(db.scalars(
        select(ProviderConfiguration).where(ProviderConfiguration.merchant_id == merchant_id)
        .order_by(ProviderConfiguration.environment, ProviderConfiguration.created_at)
    ))


def get_owned(db: Session, merchant_id: str | None, config_id: str) -> ProviderConfiguration:
    c = db.get(ProviderConfiguration, config_id)
    if c is None or (merchant_id is not None and c.merchant_id != merchant_id):
        raise NotFound("Provider configuration not found")
    return c


def create(db: Session, merchant_id: str, body: ProviderConfigCreate, actor: User, meta: RequestMeta) -> ProviderConfiguration:
    provider = db.scalar(select(PaymentProvider).where(PaymentProvider.code == body.provider_code))
    if provider is None or not provider.is_enabled:
        raise NotFound("Payment provider not available")
    if provider.code == SANDBOX:
        raise Conflict("The sandbox provider is configured automatically", code="SANDBOX_MANAGED")
    if body.environment == Environment.LIVE and not provider.is_live_capable:
        raise AppError("This provider cannot process live payments", code="PROVIDER_NOT_LIVE_CAPABLE")
    exists = db.scalar(select(ProviderConfiguration).where(
        ProviderConfiguration.merchant_id == merchant_id, ProviderConfiguration.provider_id == provider.id,
        ProviderConfiguration.environment == body.environment,
    ))
    if exists:
        raise Conflict("A configuration for this provider and environment already exists", code="DUPLICATE_PROVIDER_CONFIG")
    cfg = ProviderConfiguration(
        merchant_id=merchant_id, provider_id=provider.id, environment=body.environment,
        provider_merchant_id=body.provider_merchant_id,
        credentials_enc=encrypt_json(body.credentials) if body.credentials else None, status=S.DRAFT,
    )
    db.add(cfg)
    db.flush()
    audit.record(db, "provider_config.created", actor=actor, entity_type="provider_config", entity_id=cfg.id,
                 merchant_id=merchant_id, details={"provider": provider.code, "environment": cfg.environment,
                 "credential_fields": sorted(body.credentials)}, meta=meta)
    db.commit()
    db.refresh(cfg)
    return cfg


def _ensure_not_sandbox(cfg: ProviderConfiguration) -> None:
    if cfg.provider.code == SANDBOX:
        raise Conflict("The sandbox provider is managed by the platform", code="SANDBOX_MANAGED")


def update(db: Session, cfg: ProviderConfiguration, body: ProviderConfigUpdate, actor: User, meta: RequestMeta) -> ProviderConfiguration:
    _ensure_not_sandbox(cfg)
    if cfg.status not in (S.DRAFT, S.DISABLED):
        raise Conflict("Only draft or disabled configurations can be edited", code="CONFIG_LOCKED")
    details: dict = {}
    if body.provider_merchant_id is not None and body.provider_merchant_id != cfg.provider_merchant_id:
        details["provider_merchant_id"] = [cfg.provider_merchant_id, body.provider_merchant_id]
        cfg.provider_merchant_id = body.provider_merchant_id
    if body.credentials is not None:
        cfg.credentials_enc = encrypt_json(body.credentials) if body.credentials else None
        details["credential_fields"] = sorted(body.credentials)
    if cfg.status == S.DISABLED and details:
        cfg.status = S.DRAFT
        details["status"] = [S.DISABLED, S.DRAFT]
    if details:
        audit.record(db, "provider_config.updated", actor=actor, entity_type="provider_config", entity_id=cfg.id,
                     merchant_id=cfg.merchant_id, details=details, meta=meta)
    db.commit()
    db.refresh(cfg)
    return cfg


def _transition(db, cfg, allowed: set, target: str, action: str, actor, meta, reason=None, **fields):
    _ensure_not_sandbox(cfg)
    if cfg.status not in allowed:
        raise Conflict(f"Cannot {action} a configuration in status {cfg.status}", code="INVALID_STATUS_TRANSITION")
    previous = cfg.status
    cfg.status = target
    cfg.status_reason = reason
    for k, val in fields.items():
        setattr(cfg, k, val)
    audit.record(db, f"provider_config.{action}", actor=actor, entity_type="provider_config", entity_id=cfg.id,
                 merchant_id=cfg.merchant_id, details={"from": previous, "to": target, "reason": reason}, meta=meta)
    db.commit()
    db.refresh(cfg)
    return cfg


def submit(db, cfg, actor, meta):
    if not cfg.provider_merchant_id or not cfg.credentials_enc:
        raise AppError("Provider merchant ID and credentials are required before submitting", code="INCOMPLETE_CONFIG")
    return _transition(db, cfg, {S.DRAFT}, S.SUBMITTED, "submitted", actor, meta, submitted_at=utcnow())


def approve(db, cfg, actor, meta):
    return _transition(db, cfg, {S.SUBMITTED}, S.APPROVED, "approved", actor, meta,
                       approved_at=utcnow(), approved_by_user_id=actor.id)


def reject(db, cfg, reason, actor, meta):
    return _transition(db, cfg, {S.SUBMITTED, S.APPROVED}, S.DRAFT, "rejected", actor, meta, reason=reason)


def activate(db, cfg, actor, meta):
    # TESTED is only reachable through the provider integration test (requires a real adapter).
    return _transition(db, cfg, {S.TESTED}, S.ACTIVE, "activated", actor, meta)


def disable(db, cfg, reason, actor, meta):
    return _transition(db, cfg, {S.DRAFT, S.SUBMITTED, S.APPROVED, S.TESTED, S.ACTIVE}, S.DISABLED, "disabled",
                       actor, meta, reason=reason)


def set_provider_enabled(db: Session, provider: PaymentProvider, enabled: bool, actor: User, meta: RequestMeta) -> PaymentProvider:
    if provider.is_enabled != enabled:
        provider.is_enabled = enabled
        audit.record(db, "provider." + ("enabled" if enabled else "disabled"), actor=actor, entity_type="provider",
                     entity_id=provider.id, details={"code": provider.code}, meta=meta)
        db.commit()
        db.refresh(provider)
    return provider
