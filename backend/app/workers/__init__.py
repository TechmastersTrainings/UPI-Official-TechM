"""Background jobs. Run with `python -m app.workers` (one or more replicas; jobs are safe to run
concurrently because rows are claimed with SELECT ... FOR UPDATE SKIP LOCKED).

Phase 3 job: payment expiry. Phase 5 adds provider status polling and webhook delivery."""

import logging

from app.db.session import get_sessionmaker
from app.services import payments

log = logging.getLogger("app.worker")


def run_once() -> dict[str, int]:
    with get_sessionmaker()() as db:
        expired = payments.expire_due(db)
    if expired:
        log.info("payments_expired", extra={"count": expired})
    return {"payments_expired": expired}
