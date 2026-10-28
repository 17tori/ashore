"""Redis access with graceful degradation.

Redis is used for rate limiting, short-lived locks and the job queue. Correctness never depends on it:
idempotency is enforced by PostgreSQL constraints and row locks, so when Redis is down the app keeps
serving requests and background work waits for it to come back.
"""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import get_settings

log = logging.getLogger(__name__)

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            get_settings().redis_url, socket_connect_timeout=1, socket_timeout=2, decode_responses=True
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


async def redis_healthy() -> bool:
    try:
        return bool(await get_redis().ping())
    except (RedisError, OSError):
        return False


class _MemoryWindow:
    """Process-local fallback for rate limiting when Redis is unavailable."""

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}

    def hit(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        hits = [t for t in self._hits.get(key, []) if now - t < window]
        allowed = len(hits) < limit
        if allowed:
            hits.append(now)
        self._hits[key] = hits
        return allowed


_memory = _MemoryWindow()


async def rate_limit_hit(key: str, limit: int, window_seconds: int) -> bool:
    """Fixed-window counter. Returns True when the request is allowed."""
    bucket = f"rl:{key}:{int(time.time() // window_seconds)}"
    try:
        r = get_redis()
        count = await r.incr(bucket)
        if count == 1:
            await r.expire(bucket, window_seconds + 1)
        return count <= limit
    except (RedisError, OSError):
        log.warning("redis unavailable, using in-process rate limiter")
        return _memory.hit(key, limit, window_seconds)


class LockNotAcquired(Exception):
    pass


@asynccontextmanager
async def redis_lock(name: str, ttl_seconds: int = 120) -> AsyncIterator[None]:
    """Best-effort distributed lock. Raises LockNotAcquired if someone else holds it.

    If Redis is down the lock is skipped: callers must already be safe under concurrency
    (database constraints), the lock only avoids wasted work.
    """
    token = str(time.time_ns())
    acquired = False
    try:
        acquired = bool(await get_redis().set(f"lock:{name}", token, nx=True, ex=ttl_seconds))
        if not acquired:
            raise LockNotAcquired(name)
    except (RedisError, OSError):
        log.warning("redis unavailable, proceeding without lock", extra={"lock": name})
    try:
        yield
    finally:
        if acquired:
            try:
                r = get_redis()
                if await r.get(f"lock:{name}") == token:
                    await r.delete(f"lock:{name}")
            except (RedisError, OSError):
                pass
