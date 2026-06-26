from __future__ import annotations

import json
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings


def redis_client() -> Redis | None:
    try:
        client = Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=1)
        client.ping()
        return client
    except RedisError:
        return None


def cache_get(key: str) -> Any | None:
    client = redis_client()
    if not client:
        return None
    value = client.get(key)
    return json.loads(value) if value else None


def cache_set(key: str, value: Any, seconds: int = 60) -> None:
    client = redis_client()
    if not client:
        return
    client.setex(key, seconds, json.dumps(value, ensure_ascii=False, default=str))

