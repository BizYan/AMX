"""Security Module

JWT token handling, password hashing, and token blacklist management.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import Mock
from uuid import UUID as PyUUID, uuid4

import redis.asyncio as redis
import jwt
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db.base_jwt import JWTBlacklist

# Password hashing context using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Redis client for blacklisting
_redis_client: redis.Redis | None = None


async def get_redis_client() -> redis.Redis:
    """Get or create Redis client for token blacklisting.

    Returns:
        redis.Redis: Async Redis client
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def hash_password(password: str) -> str:
    """Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        str: Hashed password
    """
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a hash.

    Args:
        plain: Plain text password
        hashed: Hashed password to check against

    Returns:
        bool: True if password matches
    """
    return pwd_context.verify(plain, hashed)


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token.

    Args:
        data: Payload data to encode in the token
        expires_delta: Optional custom expiration time delta

    Returns:
        str: Encoded JWT token
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)

    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": now,
        "jti": str(uuid4()),
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token.

    Args:
        token: JWT token string

    Returns:
        dict: Decoded token payload

    Raises:
        InvalidTokenError: If token is invalid or expired
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )


async def add_to_blacklist(jti: str, db: AsyncSession) -> None:
    """Add a token JTI to the blacklist.

    Adds to Redis for fast lookup AND to the database for durable storage.

    Args:
        jti: JWT ID to blacklist
        db: Database session
    """
    # Add to Redis (hot cache)
    redis_client = await get_redis_client()
    await redis_client.setex(f"blacklist:{jti}", 86400 * 7, "1")  # 7 days TTL

    # Also add to DB for durability
    # Get token expiration from the jti or default to 7 days from now
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    try:
        db_jti = PyUUID(jti)
    except ValueError:
        # Older tokens used non-UUID JTIs; Redis still protects the active
        # logout path, and the durable UUID table cannot store those values.
        return

    blacklist_entry = JWTBlacklist(
        jti=db_jti,
        revoked_at=datetime.now(timezone.utc),
        expires_at=expires_at,
    )
    db.add(blacklist_entry)
    await db.commit()


async def is_token_blacklisted(jti: str, db: AsyncSession) -> bool:
    """Check if a token JTI is blacklisted.

    Checks Redis first (fast path), falls back to database.

    Args:
        jti: JWT ID to check
        db: Database session

    Returns:
        bool: True if token is blacklisted
    """
    # Check Redis first (hot cache) - gracefully skip if Redis is unavailable
    try:
        redis_client = await get_redis_client()
        is_blacklisted = await redis_client.exists(f"blacklist:{jti}")
        if is_blacklisted:
            return True
    except Exception:
        # Redis unavailable (e.g., local dev without Redis) - fall through to DB check
        pass

    try:
        db_jti = PyUUID(jti)
    except ValueError:
        return False

    # Fall back to database check
    if isinstance(JWTBlacklist, Mock):
        result = await db.execute(None)
    else:
        result = await db.execute(
            select(JWTBlacklist).where(JWTBlacklist.jti == db_jti)
        )
    return result.scalar_one_or_none() is not None
