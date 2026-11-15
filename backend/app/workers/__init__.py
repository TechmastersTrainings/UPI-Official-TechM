"""Background jobs. Run with `python -m app.workers` (one or more replicas; jobs are safe to run
concurrently because rows are claimed with SELECT ... FOR UPDATE SKIP LOCKED).

Jobs: expiry of unstarted payments, and provider-confirmed expiry of open sessions. Phase 5 adds provider status polling and webhook delivery."""

import logging

from app.db.session import get_sessionmaker
from app.services import checkout, payments

log = logging.getLogger("app.worker")


def run_once() -> dict[str, int]:
    with get_sessionmaker()() as db:
        expired = payments.expire_due(db)
        sessions = checkout.expire_sessions_due(db)
    if expired or sessions:
        log.info("payments_expired", extra={"unstarted": expired, "provider_confirmed": sessions})
    return {"payments_expired": expired, "sessions_expired": sessions}
