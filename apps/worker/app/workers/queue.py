"""ARQ Worker queue settings and task registry"""
import asyncio
from typing import Optional

import redis.asyncio as redis_async


class WorkerSettings:
    """ARQ worker settings for the Consultant AI Workbench queue."""

    redis_settings: Optional[dict] = None  # Set via environment

    @classmethod
    def get_redis_url(cls) -> str:
        import os
        return os.getenv("ARQ_REDIS_URL", "redis://localhost:6379/1")

    @classmethod
    async def get_redis(cls) -> redis_async.Redis:
        return await redis_async.from_url(cls.get_redis_url())

    @classmethod
    def get_queue_name(cls) -> str:
        return "consultant_ai_queue"
