"""JWT Blacklist Model

Separate model file for JWT blacklist to avoid circular imports.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class JWTBlacklist(Base):
    """JWT token blacklist for revoked tokens.

    This table stores JTIs of revoked tokens for security purposes.
    Redis is used as a hot cache, this table is the durable fallback.
    """

    __tablename__ = "jwt_blacklist"

    jti = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    revoked_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )