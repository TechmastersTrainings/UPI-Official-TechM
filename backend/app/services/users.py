from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.core.security import hash_password, validate_password_strength
from app.models import Role, User
from app.models.enums import PLATFORM_ROLES, ActorType, RoleName
from app.services import audit
from app.services.audit import RequestMeta
from app.services.auth import _revoke_user_sessions


def get_role(db: Session, name: str) -> Role:
    role = db.scalar(select(Role).where(Role.name == name))
    if role is None:
        raise AppError(f"Role {name} is not provisioned; run migrations", code="ROLE_MISSING", status_code=500)
    return role


def create_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    password: str,
    role: str,
    merchant_id: str | None = None,
    actor: User | None = None,
    meta: RequestMeta | None = None,
    source: str = "cli",
) -> User:
    email = email.strip().lower()
    problems = validate_password_strength(password)
    if problems:
        raise AppError("Password " + "; ".join(problems), code="WEAK_PASSWORD")
    if db.scalar(select(func.count()).select_from(User).where(User.email == email)):
        raise Conflict("A user with this email already exists", code="EMAIL_TAKEN")
    if (role in PLATFORM_ROLES) == (merchant_id is not None):
        raise AppError("Platform users have no merchant; merchant users require one", code="ROLE_SCOPE_MISMATCH")
    user = User(
        email=email,
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        role_id=get_role(db, role).id,
        merchant_id=merchant_id,
    )
    db.add(user)
    db.flush()
    audit.record(
        db, "user.created", actor=actor, actor_type=ActorType.USER if actor else ActorType.SYSTEM,
        actor_label=None if actor else source, entity_type="user",
        entity_id=user.id, merchant_id=merchant_id, details={"email": email, "role": role}, meta=meta,
    )
    return user


def list_platform_users(db: Session) -> list[User]:
    stmt = select(User).join(Role).where(Role.name.in_([r.value for r in PLATFORM_ROLES])).order_by(User.created_at)
    return list(db.scalars(stmt))


def update_platform_user(
    db: Session, *, user_id: str, actor: User, meta: RequestMeta,
    is_active: bool | None = None, role: str | None = None, full_name: str | None = None, unlock: bool = False,
) -> User:
    user = db.get(User, user_id)
    if user is None or user.role.name not in PLATFORM_ROLES:
        raise NotFound("User not found")
    changes: dict = {}
    if user.id == actor.id and (is_active is False or (role and role != user.role.name)):
        raise Forbidden("You cannot deactivate yourself or change your own role", code="SELF_MODIFICATION")

    if role and role != user.role.name:
        if role not in PLATFORM_ROLES:
            raise AppError("Role must be a platform role", code="INVALID_ROLE")
        if user.role.name == RoleName.SUPER_ADMIN:
            _ensure_another_active_super_admin(db, user.id)
        changes["role"] = [user.role.name, role]
        user.role_id = get_role(db, role).id
        db.flush()
        db.refresh(user)
        user.token_version += 1
    if is_active is not None and is_active != user.is_active:
        if not is_active and user.role.name == RoleName.SUPER_ADMIN:
            _ensure_another_active_super_admin(db, user.id)
        changes["is_active"] = [user.is_active, is_active]
        user.is_active = is_active
        if not is_active:
            user.token_version += 1
            _revoke_user_sessions(db, user.id, reason="deactivated")
    if full_name and full_name.strip() != user.full_name:
        changes["full_name"] = [user.full_name, full_name.strip()]
        user.full_name = full_name.strip()
    if unlock and (user.locked_until or user.failed_login_count):
        changes["unlocked"] = True
        user.locked_until = None
        user.failed_login_count = 0

    if changes:
        audit.record(db, "user.updated", actor=actor, entity_type="user", entity_id=user.id, details=changes, meta=meta)
    db.commit()
    db.refresh(user)
    return user


def _ensure_another_active_super_admin(db: Session, excluding_user_id: str) -> None:
    count = db.scalar(
        select(func.count())
        .select_from(User)
        .join(Role)
        .where(Role.name == RoleName.SUPER_ADMIN, User.is_active.is_(True), User.id != excluding_user_id)
    )
    if not count:
        raise Conflict("At least one active Super Admin must remain", code="LAST_SUPER_ADMIN")
