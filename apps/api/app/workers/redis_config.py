"""Redis configuration helpers for ARQ runtime wiring."""

from arq.connections import RedisSettings

from app.core.settings import settings


def require_arq_redis_url() -> str:
    redis_url = settings.ARQ_REDIS_URL.strip()
    if not redis_url:
        raise RuntimeError("ARQ_REDIS_URL is required for workflow queue execution")
    return redis_url


def arq_redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(require_arq_redis_url())
