from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.config import get_settings
from app.core.crypto import keyed_hash, random_token
from app.core.errors import AppError, Conflict, Unauthorized
from app.core.security import (
    create_access_token,
    hash_password,
    password_needs_rehash,
    validate_password_strength,
    verify_password,
)
from app.db.types import utcnow
from app.models import User, UserSession
from app.models.enums import ActorType
from app.services import audit
from app.services.audit import RequestMeta


ROTATION_GRACE_SECONDS = 15


@dataclass
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    session: UserSession


def _issue(db: Session, user: User, meta: RequestMeta, *, previous_hash: str | None = None) -> IssuedTokens:
    s = get_settings()
    refresh = random_token(48)
    session = UserSession(
        user_id=user.id,
        refresh_token_hash=keyed_hash(refresh),
        previous_token_hash=previous_hash,
        ip_address=meta.ip_address,
        user_agent=(meta.user_agent or "")[:255] or None,
        expires_at=utcnow() + timedelta(seconds=s.REFRESH_TOKEN_TTL_SECONDS),
        last_used_at=utcnow(),
    )
    db.add(session)
    db.flush()
    access, ttl = create_access_token(
        user_id=user.id, role=user.role.name, session_id=session.id, token_version=user.token_version
    )
    return IssuedTokens(access, ttl, refresh, session)


def login(db: Session, email: str, password: str, meta: RequestMeta) -> tuple[User, IssuedTokens]:
    s = get_settings()
    email = email.strip().lower()
    rate_limit.hit(f"login:ip:{meta.ip_address}", s.LOGIN_RATE_LIMIT_PER_MINUTE)
    rate_limit.hit(f"login:email:{email}", s.LOGIN_RATE_LIMIT_PER_MINUTE)

    user = db.scalar(select(User).where(User.email == email))
    now = utcnow()
    generic = Unauthorized("Invalid email or password", code="INVALID_CREDENTIALS")

    if user is None:
        verify_password(password, None)  # equalise timing
        audit.record(db, "auth.login_failed", actor_label=email, details={"reason": "unknown_email"}, meta=meta)
        db.commit()
        raise generic

    if user.locked_until and user.locked_until > now:
        audit.record(db, "auth.login_blocked", actor=user, entity_type="user", entity_id=user.id, meta=meta)
        db.commit()
        raise Unauthorized("Account temporarily locked. Try again later.", code="ACCOUNT_LOCKED")

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        details = {"reason": "bad_password", "failed_count": user.failed_login_count}
        if user.failed_login_count >= s.LOGIN_MAX_FAILED_ATTEMPTS:
            user.locked_until = now + timedelta(seconds=s.LOGIN_LOCKOUT_SECONDS)
            user.failed_login_count = 0
            details["locked_until"] = user.locked_until.isoformat()
        audit.record(db, "auth.login_failed", actor=user, entity_type="user", entity_id=user.id, details=details, meta=meta)
        db.commit()
        raise generic

    if not user.is_active:
        audit.record(db, "auth.login_failed", actor=user, entity_type="user", entity_id=user.id,
                     details={"reason": "inactive"}, meta=meta)
        db.commit()
        raise Unauthorized("Account is disabled", code="ACCOUNT_DISABLED")

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    tokens = _issue(db, user, meta)
    audit.record(db, "auth.login", actor=user, entity_type="user", entity_id=user.id,
                 details={"session_id": tokens.session.id}, meta=meta)
    db.commit()
    return user, tokens


def refresh(db: Session, refresh_token: str | None, meta: RequestMeta) -> tuple[User, IssuedTokens]:
    if not refresh_token:
        raise Unauthorized("No session", code="SESSION_MISSING")
    token_hash = keyed_hash(refresh_token)
    now = utcnow()

    session = db.scalar(select(UserSession).where(UserSession.refresh_token_hash == token_hash).with_for_update())
    if session is None:
        raise Unauthorized("Session is no longer valid", code="SESSION_INVALID")

    if session.revoked_reason == "rotated":
        if session.revoked_at and (now - session.revoked_at).total_seconds() < ROTATION_GRACE_SECONDS:
            # Two tabs refreshed at the same instant; the other one already holds the new cookie.
            raise Conflict("Session was just refreshed; retry with the current cookie", code="SESSION_ROTATED")
        # A rotated-out token being replayed means it leaked: kill every session and access token.
        _revoke_user_sessions(db, session.user_id, reason="refresh_token_reuse")
        victim = db.get(User, session.user_id)
        if victim:
            victim.token_version += 1
        audit.record(db, "auth.refresh_token_reuse", actor_type=ActorType.SYSTEM, entity_type="user",
                     entity_id=session.user_id, actor_label="system", details={"session_id": session.id}, meta=meta)
        db.commit()
        raise Unauthorized("Session is no longer valid", code="SESSION_INVALID")

    if session.revoked_at is not None or session.expires_at <= now:
        raise Unauthorized("Session expired", code="SESSION_EXPIRED")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Account is disabled", code="ACCOUNT_DISABLED")

    session.revoked_at = now
    session.revoked_reason = "rotated"
    tokens = _issue(db, user, meta, previous_hash=token_hash)
    db.commit()
    return user, tokens


def logout(db: Session, refresh_token: str | None, user: User | None, meta: RequestMeta) -> None:
    if refresh_token:
        session = db.scalar(select(UserSession).where(UserSession.refresh_token_hash == keyed_hash(refresh_token)))
        if session and session.revoked_at is None:
            session.revoked_at = utcnow()
            session.revoked_reason = "logout"
            user = user or db.get(User, session.user_id)
    if user:
        audit.record(db, "auth.logout", actor=user, entity_type="user", entity_id=user.id, meta=meta)
    db.commit()


def _revoke_user_sessions(db: Session, user_id: str, *, reason: str, except_session_id: str | None = None) -> None:
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoked_reason=reason)
    )
    if except_session_id:
        stmt = stmt.where(UserSession.id != except_session_id)
    db.execute(stmt)


def change_password(
    db: Session, user: User, session_id: str, current_password: str, new_password: str, meta: RequestMeta
) -> IssuedTokens:
    if not verify_password(current_password, user.password_hash):
        raise AppError("Current password is incorrect", code="INVALID_CURRENT_PASSWORD")
    problems = validate_password_strength(new_password)
    if problems:
        raise AppError("Password " + "; ".join(problems), code="WEAK_PASSWORD")
    if verify_password(new_password, user.password_hash):
        raise AppError("New password must differ from the current one", code="PASSWORD_REUSE")

    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    user.token_version += 1
    _revoke_user_sessions(db, user.id, reason="password_changed")
    tokens = _issue(db, user, meta)
    audit.record(db, "auth.password_changed", actor=user, entity_type="user", entity_id=user.id,
                 details={"previous_session_id": session_id}, meta=meta)
    db.commit()
    return tokens
