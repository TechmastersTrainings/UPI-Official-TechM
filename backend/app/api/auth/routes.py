from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, request_meta
from app.core.config import get_settings
from app.core.errors import Forbidden
from app.db.session import get_db
from app.models import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, LoginResponse, MeResponse, TokenResponse
from app.services import auth as auth_service
from app.services.rbac import permissions_for

router = APIRouter(prefix="/api/auth", tags=["Auth"])

REFRESH_COOKIE = "tm_refresh"
COOKIE_PATH = "/api/auth"
CLIENT_HEADER = "x-tm-client"


def _require_client_header(request: Request) -> None:
    # Cookie-authenticated endpoints require a custom header. Browsers can't add it cross-site
    # without a CORS preflight, which our allow-list rejects, so this blocks CSRF.
    if request.headers.get(CLIENT_HEADER) != "dashboard":
        raise Forbidden("Missing client header", code="CSRF_CHECK_FAILED")


def _set_refresh_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=s.REFRESH_TOKEN_TTL_SECONDS,
        httponly=True,
        secure=s.COOKIE_SECURE,
        samesite="lax",
        path=COOKIE_PATH,
        domain=s.COOKIE_DOMAIN,
    )


def _clear_refresh_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH, domain=s.COOKIE_DOMAIN)


def _me(user: User) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.name,
        merchant_id=user.merchant_id,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        permissions=sorted(permissions_for(user.role.name)),
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    _require_client_header(request)
    user, tokens = auth_service.login(db, body.email, body.password, request_meta(request))
    _set_refresh_cookie(response, tokens.refresh_token)
    return LoginResponse(access_token=tokens.access_token, expires_in=tokens.expires_in, user=_me(user))


@router.post("/refresh", response_model=LoginResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    tm_refresh: str | None = Cookie(default=None),
):
    _require_client_header(request)
    user, tokens = auth_service.refresh(db, tm_refresh, request_meta(request))
    _set_refresh_cookie(response, tokens.refresh_token)
    return LoginResponse(access_token=tokens.access_token, expires_in=tokens.expires_in, user=_me(user))


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    tm_refresh: str | None = Cookie(default=None),
):
    _require_client_header(request)
    auth_service.logout(db, tm_refresh, None, request_meta(request))
    _clear_refresh_cookie(response)
    response.status_code = 204
    return response


@router.get("/me", response_model=MeResponse)
def me(current: CurrentUser = Depends(get_current_user)):
    return _me(current.user)


@router.post("/change-password", response_model=TokenResponse)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tokens = auth_service.change_password(
        db, current.user, current.session_id, body.current_password, body.new_password, request_meta(request)
    )
    _set_refresh_cookie(response, tokens.refresh_token)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)
