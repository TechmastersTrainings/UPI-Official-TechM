from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, Unauthorized
from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.models import User, UserSession
from app.services.audit import RequestMeta
from app.services.rbac import permissions_for

_bearer = HTTPBearer(auto_error=False)


def request_meta(request: Request) -> RequestMeta:
    return RequestMeta(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@dataclass
class CurrentUser:
    user: User
    session_id: str
    permissions: frozenset[str]


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise Unauthorized("Authentication required", code="AUTH_REQUIRED")
    try:
        claims = decode_access_token(creds.credentials)
    except TokenError as exc:
        raise Unauthorized(exc.message, code=exc.code) from exc

    user = db.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise Unauthorized("Account is disabled", code="ACCOUNT_DISABLED")
    if user.token_version != claims.get("tv"):
        raise Unauthorized("Session was invalidated", code="TOKEN_REVOKED")
    session = db.get(UserSession, claims.get("sid"))
    # A rotated session stays valid for its already-issued access token until expiry,
    # but logout / password change / deactivation revoke immediately.
    if session is None or session.user_id != user.id or (
        session.revoked_at is not None and session.revoked_reason != "rotated"
    ):
        raise Unauthorized("Session was invalidated", code="TOKEN_REVOKED")
    return CurrentUser(user=user, session_id=session.id, permissions=permissions_for(user.role.name))


def require(*perms: str) -> Callable[..., CurrentUser]:
    def _guard(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        missing = [p for p in perms if p not in current.permissions]
        if missing:
            raise Forbidden("You do not have permission to perform this action", code="PERMISSION_DENIED")
        return current

    return _guard
