"""Fixed-window rate limiter. Redis-backed so limits hold across API replicas; falls back to an
in-process window only in development/test or if Redis is temporarily unreachable."""

import logging
import threading
import time

import redis

from app.core.errors import TooManyRequests
from app.core.redis import get_redis

log = logging.getLogger(__name__)

_local: dict[str, tuple[int, int]] = {}
_lock = threading.Lock()


def _hit_local(key: str, window: int) -> int:
    bucket = int(time.time()) // window
    with _lock:
        b, count = _local.get(key, (bucket, 0))
        count = count + 1 if b == bucket else 1
        _local[key] = (bucket, count)
        return count


def hit(key: str, limit: int, window_seconds: int = 60) -> None:
    """Register one hit for `key`; raise TooManyRequests when over `limit` in the window."""
    full_key = f"rl:{key}:{int(time.time()) // window_seconds}"
    client = get_redis()
    count: int
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incr(full_key)
            pipe.expire(full_key, window_seconds + 1)
            count = int(pipe.execute()[0])
        except redis.RedisError:
            log.warning("rate_limit_redis_unavailable", extra={"key": key})
            count = _hit_local(key, window_seconds)
    else:
        count = _hit_local(key, window_seconds)
    if count > limit:
        raise TooManyRequests("Too many requests, please retry later")


def reset_local() -> None:
    with _lock:
        _local.clear()
