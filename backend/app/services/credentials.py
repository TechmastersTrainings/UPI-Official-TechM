"""Gateway API credentials.

key_id  : tm_test_XXXXXXXXXXXXXXXX / tm_live_...   (public identifier, selects the environment)
secret  : tmsk_test_<43 url-safe chars>             (256 bits; shown once; stored only as HMAC-SHA256)
"""

import secrets
import string
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto import constant_time_equals, keyed_hash
from app.core.errors import AppError, Forbidden, NotFound, Unauthorized
from app.db.types import utcnow
from app.models import ApiCredential, Merchant, User
from app.models.enums import CredentialStatus, Environment, MerchantStatus
from app.services import audit
from app.services.audit import RequestMeta

MAX_ACTIVE_PER_ENV = 2  # allows zero-downtime rotation: create new, deploy, revoke old
_ALNUM = string.ascii_letters + string.digits
LAST_USED_RESOLUTION = timedelta(minutes=1)


def _new_pair(environment: str) -> tuple[str, str]:
    env = environment.lower()
    key_id = f"tm_{env}_" + "".join(secrets.choice(_ALNUM) for _ in range(16))
    secret = f"tmsk_{env}_" + secrets.token_urlsafe(32)
    return key_id, secret


def list_for(db: Session, merchant_id: str) -> list[ApiCredential]:
    return list(db.scalars(
        select(ApiCredential).where(ApiCredential.merchant_id == merchant_id).order_by(ApiCredential.created_at.desc())
    ))


def get_owned(db: Session, merchant_id: str, credential_id: str) -> ApiCredential:
    c = db.get(ApiCredential, credential_id)
    if c is None or c.merchant_id != merchant_id:
        raise NotFound("Credential not found")
    return c


def _issue(db: Session, merchant: Merchant, environment: str, label: str | None, actor: User) -> tuple[ApiCredential, str]:
    key_id, secret = _new_pair(environment)
    cred = ApiCredential(
        merchant_id=merchant.id, environment=environment, key_id=key_id, secret_hash=keyed_hash(secret),
        secret_prefix=secret[:14], label=label, status=CredentialStatus.ACTIVE, created_by_user_id=actor.id,
    )
    db.add(cred)
    db.flush()
    return cred, secret


def generate(db: Session, merchant: Merchant, environment: str, label: str | None, actor: User, meta: RequestMeta) -> tuple[ApiCredential, str]:
    if environment == Environment.LIVE and not merchant.live_enabled:
        raise Forbidden("Live mode is not enabled for this merchant", code="LIVE_NOT_ENABLED")
    active = db.scalar(select(func.count()).select_from(ApiCredential).where(
        ApiCredential.merchant_id == merchant.id, ApiCredential.environment == environment,
        ApiCredential.status == CredentialStatus.ACTIVE,
    ))
    if active >= MAX_ACTIVE_PER_ENV:
        raise AppError(
            f"At most {MAX_ACTIVE_PER_ENV} active {environment.lower()} keys; revoke or regenerate one first",
            code="LIMIT_REACHED",
        )
    cred, secret = _issue(db, merchant, environment, label, actor)
    audit.record(db, "api_credential.generated", actor=actor, entity_type="api_credential", entity_id=cred.id,
                 merchant_id=merchant.id, details={"key_id": cred.key_id, "environment": environment}, meta=meta)
    db.commit()
    db.refresh(cred)
    return cred, secret


def revoke(db: Session, cred: ApiCredential, actor: User, meta: RequestMeta, *, commit: bool = True) -> ApiCredential:
    if cred.status != CredentialStatus.REVOKED:
        cred.status = CredentialStatus.REVOKED
        cred.revoked_at = utcnow()
        audit.record(db, "api_credential.revoked", actor=actor, entity_type="api_credential", entity_id=cred.id,
                     merchant_id=cred.merchant_id, details={"key_id": cred.key_id}, meta=meta)
    if commit:
        db.commit()
        db.refresh(cred)
    return cred


def regenerate(db: Session, merchant: Merchant, cred: ApiCredential, actor: User, meta: RequestMeta) -> tuple[ApiCredential, str]:
    """Atomically revoke `cred` and issue a replacement in the same environment."""
    if cred.status != CredentialStatus.ACTIVE:
        raise AppError("Only active keys can be regenerated", code="CREDENTIAL_REVOKED")
    if cred.environment == Environment.LIVE and not merchant.live_enabled:
        raise Forbidden("Live mode is not enabled for this merchant", code="LIVE_NOT_ENABLED")
    revoke(db, cred, actor, meta, commit=False)
    new, secret = _issue(db, merchant, cred.environment, cred.label, actor)
    audit.record(db, "api_credential.regenerated", actor=actor, entity_type="api_credential", entity_id=new.id,
                 merchant_id=merchant.id, details={"replaces": cred.key_id, "key_id": new.key_id}, meta=meta)
    db.commit()
    db.refresh(new)
    return new, secret


def authenticate(db: Session, key_id: str, secret: str) -> tuple[ApiCredential, Merchant]:
    """Validate a gateway API key pair. Used by the /api/v1 dependency (Phase 3).
    Failure reasons are deliberately not distinguished to callers."""
    invalid = Unauthorized("Invalid API credentials", code="INVALID_API_KEY")
    if not key_id or not secret or len(key_id) > 64 or len(secret) > 128:
        raise invalid
    cred = db.scalar(select(ApiCredential).where(ApiCredential.key_id == key_id))
    if cred is None:
        keyed_hash(secret)  # keep timing similar
        raise invalid
    if not constant_time_equals(keyed_hash(secret), cred.secret_hash) or cred.status != CredentialStatus.ACTIVE:
        raise invalid
    merchant = db.get(Merchant, cred.merchant_id)
    if merchant is None or merchant.status in (MerchantStatus.SUSPENDED, MerchantStatus.REJECTED):
        raise Forbidden("Merchant account is not active", code="MERCHANT_NOT_ACTIVE")
    if not merchant.api_access_enabled:
        raise Forbidden("API access is disabled for this merchant", code="API_ACCESS_DISABLED")
    if cred.environment == Environment.LIVE and (not merchant.live_enabled or merchant.status != MerchantStatus.ACTIVE):
        raise Forbidden("Live mode is not enabled for this merchant", code="LIVE_NOT_ENABLED")
    now = utcnow()
    if cred.last_used_at is None or now - cred.last_used_at > LAST_USED_RESOLUTION:
        cred.last_used_at = now
        db.commit()
    return cred, merchant
