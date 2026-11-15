from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.errors import AppError, Conflict, NotFound
from app.db.types import utcnow
from app.models import (
    Merchant,
    MerchantBankAccount,
    MerchantProfile,
    PaymentProvider,
    ProviderConfiguration,
    User,
    WebhookConfiguration,
)
from app.models.enums import (
    Environment,
    MerchantStatus,
    ProviderConfigStatus,
    RoleName,
    VerificationStatus,
)
from app.schemas.merchant import MerchantProfileUpdate, MerchantRegistrationRequest
from app.services import audit
from app.services.audit import RequestMeta
from app.services.users import create_user

REGISTRATIONS_PER_IP_PER_HOUR = 5
SANDBOX_PROVIDER_CODE = "sandbox"


def register(db: Session, body: MerchantRegistrationRequest, meta: RequestMeta) -> tuple[Merchant, User]:
    rate_limit.hit(f"register:ip:{meta.ip_address}", REGISTRATIONS_PER_IP_PER_HOUR, 3600)
    b = body.business
    business_email = str(b.business_email).lower()
    if db.scalar(select(func.count()).select_from(Merchant).where(Merchant.business_email == business_email)):
        raise Conflict("A merchant with this business email is already registered", code="BUSINESS_EMAIL_TAKEN")

    merchant = Merchant(
        business_name=b.business_name,
        legal_business_name=b.legal_business_name,
        business_email=business_email,
        mobile=b.mobile,
        business_type=b.business_type,
        website_url=b.website_url,
        status=MerchantStatus.PENDING_REVIEW,
    )
    db.add(merchant)
    db.flush()
    db.add(_profile_from(merchant.id, body.address.model_dump(), body.contact.model_dump()))

    owner = create_user(
        db, email=str(body.owner.email), full_name=body.owner.full_name, password=body.owner.password,
        role=RoleName.MERCHANT_ADMIN, merchant_id=merchant.id, meta=meta, source="self_registration",
    )

    # Every merchant gets the TEST-only simulator so the full lifecycle can be exercised without money.
    sandbox = db.scalar(select(PaymentProvider).where(PaymentProvider.code == SANDBOX_PROVIDER_CODE))
    if sandbox is not None:
        db.add(ProviderConfiguration(
            merchant_id=merchant.id, provider_id=sandbox.id, environment=Environment.TEST,
            provider_merchant_id=merchant.id, status=ProviderConfigStatus.ACTIVE,
            status_reason="Built-in sandbox simulator", approved_at=utcnow(), integration_tested_at=utcnow(),
        ))

    audit.record(
        db, "merchant.registered", actor=owner, entity_type="merchant", entity_id=merchant.id,
        merchant_id=merchant.id, details={"business_name": merchant.business_name, "business_email": business_email},
        meta=meta,
    )
    db.commit()
    db.refresh(merchant)
    return merchant, owner


def _profile_from(merchant_id: str, address: dict, contact: dict) -> MerchantProfile:
    return MerchantProfile(merchant_id=merchant_id, **address, **contact)


def update_profile(db: Session, merchant: Merchant, body: MerchantProfileUpdate, actor: User, meta: RequestMeta) -> Merchant:
    changes: dict = {}
    for field in ("business_name", "legal_business_name", "mobile", "business_type", "website_url"):
        new = getattr(body, field)
        if new is not None and new != getattr(merchant, field):
            changes[field] = [getattr(merchant, field), new]
            setattr(merchant, field, new)
    profile = merchant.profile
    for section in (body.address, body.contact):
        if section is None:
            continue
        for field, new in section.model_dump().items():
            if new != getattr(profile, field):
                changes[field] = [getattr(profile, field), new]
                setattr(profile, field, new)
    if changes:
        audit.record(db, "merchant.profile_updated", actor=actor, entity_type="merchant", entity_id=merchant.id,
                     merchant_id=merchant.id, details=changes, meta=meta)
    db.commit()
    db.refresh(merchant)
    return merchant


# ---------- Live readiness ----------
def live_readiness(db: Session, merchant: Merchant) -> dict:
    live_cfgs = db.scalars(
        select(ProviderConfiguration).join(PaymentProvider).where(
            ProviderConfiguration.merchant_id == merchant.id,
            ProviderConfiguration.environment == Environment.LIVE,
            PaymentProvider.is_live_capable.is_(True),
            PaymentProvider.is_enabled.is_(True),
        )
    ).all()
    approved = [c for c in live_cfgs if c.status in (ProviderConfigStatus.APPROVED, ProviderConfigStatus.TESTED, ProviderConfigStatus.ACTIVE)]
    tested = [c for c in live_cfgs if c.integration_tested_at is not None and c.status in (ProviderConfigStatus.TESTED, ProviderConfigStatus.ACTIVE)]
    active = [c for c in live_cfgs if c.status == ProviderConfigStatus.ACTIVE]
    bank = db.scalar(select(MerchantBankAccount).where(
        MerchantBankAccount.merchant_id == merchant.id, MerchantBankAccount.environment == Environment.LIVE,
        MerchantBankAccount.is_default.is_(True), MerchantBankAccount.is_active.is_(True),
    ))
    hook = db.scalar(select(WebhookConfiguration).where(
        WebhookConfiguration.merchant_id == merchant.id, WebhookConfiguration.environment == Environment.LIVE,
    ))
    profile = merchant.profile
    any_live_provider = db.scalar(
        select(func.count()).select_from(PaymentProvider).where(
            PaymentProvider.is_live_capable.is_(True), PaymentProvider.is_enabled.is_(True)
        )
    )

    items = [
        ("merchant_active", "Merchant approved by TechMasters", merchant.status == MerchantStatus.ACTIVE,
         f"Current status: {merchant.status}"),
        ("kyc_details", "PAN recorded in business profile", bool(profile and profile.pan), None),
        ("provider_approved", "Payment provider onboarding approved", bool(approved),
         None if any_live_provider else "No live-capable payment provider is integrated on the platform yet"),
        ("provider_tested", "Provider integration tested", bool(tested), None),
        ("provider_active", "Live provider configuration active", bool(active), None),
        ("bank_verified", "Default live bank account verified",
         bool(bank and bank.verification_status == VerificationStatus.VERIFIED),
         None if bank else "No default live bank account"),
        ("webhook_validated", "Live webhook endpoint validated",
         bool(hook and hook.is_active and hook.validated_at is not None),
         None if hook else "No live webhook configured"),
    ]
    out = [{"key": k, "label": label, "met": met, "detail": None if met else detail} for k, label, met, detail in items]
    return {"ready": all(i["met"] for i in out), "items": out}


# ---------- Admin ----------
def get(db: Session, merchant_id: str) -> Merchant:
    m = db.get(Merchant, merchant_id)
    if m is None:
        raise NotFound("Merchant not found")
    return m


def search(db: Session, *, q: str | None, status: str | None, page: int, page_size: int) -> tuple[list[Merchant], int]:
    conds = []
    if q:
        like = q.strip()
        conds.append(or_(
            Merchant.business_name.contains(like, autoescape=True),
            Merchant.legal_business_name.contains(like, autoescape=True),
            Merchant.business_email.startswith(like.lower(), autoescape=True),
            Merchant.id == like,
        ))
    if status:
        conds.append(Merchant.status == status)
    total = db.scalar(select(func.count()).select_from(Merchant).where(*conds)) or 0
    rows = db.scalars(
        select(Merchant).where(*conds).order_by(Merchant.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return list(rows), total


_TRANSITIONS = {
    "approve": ({MerchantStatus.PENDING_REVIEW}, MerchantStatus.ACTIVE),
    "reject": ({MerchantStatus.PENDING_REVIEW}, MerchantStatus.REJECTED),
    "suspend": ({MerchantStatus.ACTIVE}, MerchantStatus.SUSPENDED),
    "reactivate": ({MerchantStatus.SUSPENDED}, MerchantStatus.ACTIVE),
    "reopen": ({MerchantStatus.REJECTED}, MerchantStatus.PENDING_REVIEW),
}


def change_status(db: Session, merchant: Merchant, action: str, reason: str | None, actor: User, meta: RequestMeta) -> Merchant:
    allowed_from, target = _TRANSITIONS[action]
    if merchant.status not in allowed_from:
        raise Conflict(f"Cannot {action} a merchant in status {merchant.status}", code="INVALID_STATUS_TRANSITION")
    if action in ("reject", "suspend") and not reason:
        raise AppError("A reason is required", code="REASON_REQUIRED")
    previous = merchant.status
    merchant.status = target
    merchant.status_reason = reason
    details = {"from": previous, "to": target, "reason": reason}
    if action == "approve" and merchant.approved_at is None:
        merchant.approved_at = utcnow()
        merchant.approved_by_user_id = actor.id
    if target == MerchantStatus.SUSPENDED and merchant.live_enabled:
        # Suspension turns live mode off; it must be re-enabled explicitly after review.
        merchant.live_enabled = False
        details["live_disabled"] = True
    audit.record(db, f"merchant.{action}", actor=actor, entity_type="merchant", entity_id=merchant.id,
                 merchant_id=merchant.id, details=details, meta=meta)
    db.commit()
    db.refresh(merchant)
    return merchant


def set_live(db: Session, merchant: Merchant, enabled: bool, actor: User, meta: RequestMeta) -> Merchant:
    if enabled == merchant.live_enabled:
        return merchant
    if enabled:
        readiness = live_readiness(db, merchant)
        if not readiness["ready"]:
            raise Conflict(
                "Live mode prerequisites are not met",
                code="LIVE_PREREQUISITES_UNMET",
                details=[i for i in readiness["items"] if not i["met"]],
            )
        merchant.live_enabled_at = utcnow()
    merchant.live_enabled = enabled
    audit.record(db, "merchant.live_enabled" if enabled else "merchant.live_disabled", actor=actor,
                 entity_type="merchant", entity_id=merchant.id, merchant_id=merchant.id, meta=meta)
    db.commit()
    db.refresh(merchant)
    return merchant


def set_api_access(db: Session, merchant: Merchant, enabled: bool, actor: User, meta: RequestMeta) -> Merchant:
    if merchant.api_access_enabled != enabled:
        merchant.api_access_enabled = enabled
        audit.record(db, "merchant.api_access_" + ("enabled" if enabled else "disabled"), actor=actor,
                     entity_type="merchant", entity_id=merchant.id, merchant_id=merchant.id, meta=meta)
        db.commit()
        db.refresh(merchant)
    return merchant


def merchant_users(db: Session, merchant_id: str) -> list[User]:
    return list(db.scalars(select(User).where(User.merchant_id == merchant_id).order_by(User.created_at)))
