"""Background jobs. Run with `python -m app.workers` (one or more replicas; jobs are safe to run
concurrently because rows are claimed with SELECT ... FOR UPDATE SKIP LOCKED).

Jobs: expiry of unstarted payments, provider status polling (and provider-confirmed expiry) of open
sessions, and outbound webhook delivery with retries. Phase 5 adds provider status polling and webhook delivery."""

import logging

from app.db.session import get_sessionmaker
from app.services import checkout, payments, verification, webhooks

log = logging.getLogger("app.worker")


def run_once() -> dict[str, int]:
    with get_sessionmaker()() as db:
        expired = payments.expire_due(db)
        polled = verification.poll_due(db)
        sessions = checkout.expire_sessions_due(db)
        delivered = webhooks.deliver_due(db)
    result = {"payments_expired": expired, "polled": polled, "sessions_expired": sessions, "webhooks_attempted": delivered}
    if any(result.values()):
        log.info("worker_tick", extra=result)
    return result
