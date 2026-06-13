"""Quota Service Module

Manages tenant quotas for API calls, storage, documents, users, and exports.
"""

from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.ops.models import QuotaUsage
from app.services.cache_service import acquire_lock, release_lock


# Quota type constants
class QuotaType:
    """Quota type constants."""

    API_CALLS = "API_CALLS"
    STORAGE_BYTES = "STORAGE_BYTES"
    DOCUMENT_COUNT = "DOCUMENT_COUNT"
    USER_COUNT = "USER_COUNT"
    EXPORT_COUNT = "EXPORT_COUNT"


class QuotaExceededError(Exception):
    """Exception raised when quota is exceeded."""

    def __init__(self, quota_type: str, limit: float, used: float):
        self.quota_type = quota_type
        self.limit = limit
        self.used = used
        super().__init__(f"Quota {quota_type} exceeded: {used}/{limit}")


class QuotaService:
    """Service for managing tenant quotas.

    Tracks usage against defined limits and enforces quota restrictions.
    Supports period-based quotas (daily, weekly, monthly, eternal).
    """

    def __init__(self, db: AsyncSession):
        """Initialize quota service.

        Args:
            db: Async SQLAlchemy session
        """
        self.db = db

    async def check_quota(
        self,
        tenant_id: UUID,
        quota_type: str,
        amount: float = 1,
    ) -> bool:
        """Check if quota allows the requested amount.

        Args:
            tenant_id: Tenant UUID
            quota_type: Type of quota (e.g., "API_CALLS")
            amount: Amount to check (default 1)

        Returns:
            True if quota allows operation, False otherwise
        """
        usage = await self.get_quota_usage(tenant_id, quota_type)

        if usage is None:
            # No quota defined, allow by default
            return True

        # Check if adding amount would exceed limit
        return (usage.used_amount + amount) <= usage.limit_amount

    async def increment_quota(
        self,
        tenant_id: UUID,
        quota_type: str,
        amount: float = 1,
    ) -> None:
        """Increment quota usage.

        Args:
            tenant_id: Tenant UUID
            quota_type: Type of quota
            amount: Amount to increment (default 1)

        Raises:
            QuotaExceededError: If increment would exceed limit
        """
        # Check if increment would exceed
        if not await self.check_quota(tenant_id, quota_type, amount):
            usage = await self.get_quota_usage(tenant_id, quota_type)
            if usage:
                raise QuotaExceededError(
                    quota_type,
                    usage.limit_amount,
                    usage.used_amount,
                )

        # Upsert quota usage
        result = await self.db.execute(
            select(QuotaUsage).where(
                QuotaUsage.tenant_id == tenant_id,
                QuotaUsage.quota_type == quota_type,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.used_amount += amount
            await self.db.flush()
            await self.db.refresh(existing)
        else:
            # Create new usage record with default limit
            usage = QuotaUsage(
                tenant_id=tenant_id,
                quota_type=quota_type,
                used_amount=amount,
                limit_amount=self._get_default_limit(quota_type),
                period="monthly",
            )
            self.db.add(usage)
            await self.db.flush()

    async def get_quota_usage(
        self,
        tenant_id: UUID,
        quota_type: str,
    ) -> QuotaUsage | None:
        """Get current quota usage for a tenant and type.

        Args:
            tenant_id: Tenant UUID
            quota_type: Type of quota

        Returns:
            QuotaUsage record or None if not found
        """
        result = await self.db.execute(
            select(QuotaUsage).where(
                QuotaUsage.tenant_id == tenant_id,
                QuotaUsage.quota_type == quota_type,
            )
        )
        return result.scalar_one_or_none()

    async def get_all_quotas(self, tenant_id: UUID) -> list[QuotaUsage]:
        """Get all quotas for a tenant.

        Args:
            tenant_id: Tenant UUID

        Returns:
            List of QuotaUsage records
        """
        result = await self.db.execute(
            select(QuotaUsage).where(QuotaUsage.tenant_id == tenant_id)
        )
        return list(result.scalars().all())

    async def reset_quota(
        self,
        tenant_id: UUID,
        quota_type: str,
    ) -> None:
        """Reset quota usage to zero (admin operation).

        Args:
            tenant_id: Tenant UUID
            quota_type: Type of quota to reset
        """
        await self.db.execute(
            update(QuotaUsage)
            .where(
                QuotaUsage.tenant_id == tenant_id,
                QuotaUsage.quota_type == quota_type,
            )
            .values(used_amount=0)
        )
        await self.db.flush()

    async def set_quota_limit(
        self,
        tenant_id: UUID,
        quota_type: str,
        limit: float,
        period: str = "monthly",
    ) -> QuotaUsage:
        """Set quota limit for a tenant (admin operation).

        Args:
            tenant_id: Tenant UUID
            quota_type: Type of quota
            limit: New limit value
            period: Quota period ("daily", "weekly", "monthly", "eternal")

        Returns:
            Updated or created QuotaUsage record
        """
        result = await self.db.execute(
            select(QuotaUsage).where(
                QuotaUsage.tenant_id == tenant_id,
                QuotaUsage.quota_type == quota_type,
            )
        )
        existing = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if existing:
            existing.limit_amount = limit
            existing.period = period
            existing.reset_at = self._calculate_reset_time(period, now)
            await self.db.flush()
            await self.db.refresh(existing)
            return existing
        else:
            # Create new quota
            usage = QuotaUsage(
                tenant_id=tenant_id,
                quota_type=quota_type,
                used_amount=0,
                limit_amount=limit,
                period=period,
                reset_at=self._calculate_reset_time(period, now),
            )
            self.db.add(usage)
            await self.db.flush()
            await self.db.refresh(usage)
            return usage

    def _get_default_limit(self, quota_type: str) -> float:
        """Get default limit for a quota type.

        Args:
            quota_type: Type of quota

        Returns:
            Default limit value
        """
        defaults = {
            QuotaType.API_CALLS: 10000,
            QuotaType.STORAGE_BYTES: 10 * 1024 * 1024 * 1024,  # 10 GB
            QuotaType.DOCUMENT_COUNT: 1000,
            QuotaType.USER_COUNT: 50,
            QuotaType.EXPORT_COUNT: 100,
        }
        return defaults.get(quota_type, 0)

    def _calculate_reset_time(self, period: str, now: datetime) -> datetime:
        """Calculate next reset time based on period.

        Args:
            period: Period string ("daily", "weekly", "monthly", "eternal")
            now: Current datetime

        Returns:
            Next reset datetime or None for eternal
        """
        if period == "daily":
            return now + timedelta(days=1)
        elif period == "weekly":
            return now + timedelta(weeks=1)
        elif period == "monthly":
            # Next month
            if now.month == 12:
                return datetime(now.year + 1, 1, now.day, tzinfo=timezone.utc)
            else:
                return datetime(now.year, now.month + 1, now.day, tzinfo=timezone.utc)
        else:
            return None  # Eternal, no reset

    async def check_and_increment(
        self,
        tenant_id: UUID,
        quota_type: str,
        amount: float = 1,
    ) -> None:
        """Atomically check quota and increment if allowed.

        Args:
            tenant_id: Tenant UUID
            quota_type: Type of quota
            amount: Amount to increment

        Raises:
            QuotaExceededError: If quota exceeded
        """
        lock_name = f"quota:{quota_type}"
        tenant_id_str = str(tenant_id)

        lock_acquired = await acquire_lock(lock_name, tenant_id_str, timeout=10, ttl=60)
        if not lock_acquired:
            raise QuotaExceededError(quota_type, 0, 0)

        try:
            if not await self.check_quota(tenant_id, quota_type, amount):
                usage = await self.get_quota_usage(tenant_id, quota_type)
                raise QuotaExceededError(
                    quota_type,
                    usage.limit_amount if usage else 0,
                    usage.used_amount if usage else 0,
                )

            await self.increment_quota(tenant_id, quota_type, amount)
        finally:
            await release_lock(lock_name, tenant_id_str)


def create_quota_service(db: AsyncSession) -> QuotaService:
    """Factory function to create QuotaService instance.

    Args:
        db: Async SQLAlchemy session

    Returns:
        QuotaService instance
    """
    return QuotaService(db)