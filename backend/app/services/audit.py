from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.logging import request_id_ctx
from app.core.masking import redact
from app.models import AuditLog, User
from app.models.enums import ActorType


@dataclass(frozen=True)
class RequestMeta:
    ip_address: str | None = None
    user_agent: str | None = None


def record(
    db: Session,
    action: str,
    *,
    actor: User | None = None,
    actor_type: ActorType = ActorType.USER,
    actor_label: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    merchant_id: str | None = None,
    details: dict | None = None,
    meta: RequestMeta | None = None,
) -> AuditLog:
    """Add an audit entry to the caller's transaction (committed together with the change)."""
    entry = AuditLog(
        actor_type=actor_type,
        actor_user_id=actor.id if actor else None,
        actor_label=actor_label or (actor.email if actor else None),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        merchant_id=merchant_id,
        ip_address=meta.ip_address if meta else None,
        user_agent=(meta.user_agent or "")[:255] if meta else None,
        request_id=request_id_ctx.get(),
        details=redact(details) if details else None,
    )
    db.add(entry)
    return entry
