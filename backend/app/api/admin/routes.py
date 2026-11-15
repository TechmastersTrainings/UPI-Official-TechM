from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, request_meta, require
from app.db.session import get_db
from app.models import AuditLog
from app.schemas.admin import AuditLogOut, CreatePlatformUserRequest, Page, UpdatePlatformUserRequest
from app.schemas.auth import UserOut
from app.services import dashboard, users
from app.services.rbac import Perm

router = APIRouter(prefix="/api/admin", tags=["Super Admin"])

EnvParam = Literal["LIVE", "TEST"]


def _user_out(u) -> UserOut:
    return UserOut(
        id=u.id, email=u.email, full_name=u.full_name, role=u.role.name, merchant_id=u.merchant_id,
        is_active=u.is_active, last_login_at=u.last_login_at, locked_until=u.locked_until, created_at=u.created_at,
    )


@router.get("/dashboard/summary")
def dashboard_summary(
    environment: EnvParam = "LIVE",
    _: CurrentUser = Depends(require(Perm.DASHBOARD_VIEW)),
    db: Session = Depends(get_db),
):
    return dashboard.summary(db, environment)


@router.get("/dashboard/timeseries")
def dashboard_timeseries(
    environment: EnvParam = "LIVE",
    days: int = Query(30, ge=1, le=366),
    _: CurrentUser = Depends(require(Perm.DASHBOARD_VIEW)),
    db: Session = Depends(get_db),
):
    return dashboard.timeseries(db, environment, days)


@router.get("/dashboard/activity")
def dashboard_activity(
    environment: EnvParam = "LIVE",
    limit: int = Query(10, ge=1, le=50),
    _: CurrentUser = Depends(require(Perm.DASHBOARD_VIEW)),
    db: Session = Depends(get_db),
):
    return dashboard.recent_activity(db, environment, limit)


@router.get("/audit-logs", response_model=Page[AuditLogOut])
def audit_logs(
    action: str | None = Query(None, max_length=64),
    actor: str | None = Query(None, max_length=255, description="Actor email (prefix match)"),
    entity_type: str | None = Query(None, max_length=64),
    entity_id: str | None = Query(None, max_length=64),
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    _: CurrentUser = Depends(require(Perm.AUDIT_VIEW)),
    db: Session = Depends(get_db),
):
    conds = []
    if action:
        conds.append(AuditLog.action.startswith(action, autoescape=True))
    if actor:
        conds.append(AuditLog.actor_label.startswith(actor.lower(), autoescape=True))
    if entity_type:
        conds.append(AuditLog.entity_type == entity_type)
    if entity_id:
        conds.append(AuditLog.entity_id == entity_id)
    if date_from:
        conds.append(AuditLog.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        conds.append(AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))

    total = db.scalar(select(func.count()).select_from(AuditLog).where(*conds))
    rows = db.scalars(
        select(AuditLog).where(*conds).order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page(items=[AuditLogOut.model_validate(r) for r in rows], total=total or 0, page=page, page_size=page_size)


@router.get("/users", response_model=list[UserOut])
def list_users(_: CurrentUser = Depends(require(Perm.PLATFORM_USERS_VIEW)), db: Session = Depends(get_db)):
    return [_user_out(u) for u in users.list_platform_users(db)]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: CreatePlatformUserRequest,
    request: Request,
    current: CurrentUser = Depends(require(Perm.PLATFORM_USERS_MANAGE)),
    db: Session = Depends(get_db),
):
    user = users.create_user(
        db, email=body.email, full_name=body.full_name, password=body.password, role=body.role,
        actor=current.user, meta=request_meta(request),
    )
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    body: UpdatePlatformUserRequest,
    request: Request,
    current: CurrentUser = Depends(require(Perm.PLATFORM_USERS_MANAGE)),
    db: Session = Depends(get_db),
):
    user = users.update_platform_user(
        db, user_id=user_id, actor=current.user, meta=request_meta(request),
        is_active=body.is_active, role=body.role, full_name=body.full_name, unlock=body.unlock,
    )
    return _user_out(user)
