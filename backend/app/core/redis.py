import logging
from functools import lru_cache

import redis

from app.core.config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def get_redis() -> "redis.Redis | None":
    url = get_settings().REDIS_URL
    if not url:
        return None
    return redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2, decode_responses=True)


def redis_healthy() -> bool:
    client = get_redis()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except redis.RedisError:
        return False
