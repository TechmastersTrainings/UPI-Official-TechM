import logging
import signal
import threading

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.workers import run_once

log = logging.getLogger("app.worker")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    log.info("worker_started", extra={"interval_seconds": settings.WORKER_INTERVAL_SECONDS})
    while not stop.is_set():
        try:
            run_once()
        except Exception:
            log.exception("worker_tick_failed")  # keep running; the next tick retries
        stop.wait(settings.WORKER_INTERVAL_SECONDS)
    log.info("worker_stopped")


if __name__ == "__main__":
    main()
