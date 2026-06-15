"""Database Session Module

Async SQLAlchemy engine and session management.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import settings

engine_kwargs = {
    "pool_pre_ping": True,
    "echo": settings.DEBUG,
}
if not settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs.update(
        pool_size=20,
        max_overflow=10,
    )

# Create async engine with connection pool settings
async_engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

# Async session maker
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get async database session.

    Yields:
        AsyncSession: Async SQLAlchemy session
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
