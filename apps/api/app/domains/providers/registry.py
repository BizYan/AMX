"""Provider Registry Service

Manages provider registration, versioning, and lifecycle.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.providers.models import (
    Provider,
    ProviderVersion,
    ProviderCapability,
    ProviderRun,
    ProviderHealth,
    ProviderType,
    ProviderStatus,
    RunStatus,
    HealthStatus,
)
from app.domains.providers.contracts import (
    ProviderError,
    LLMContract,
    GraphifyContract,
    GitNexusContract,
)
from app.domains.providers.credential_boundary import (
    sanitize_error_message,
    validate_provider_config_boundary,
)


class ProviderRegistry:
    """Registry service for managing providers.

    Handles provider CRUD operations, versioning, and status management.
    """

    def __init__(self, db: AsyncSession):
        """Initialize registry with database session.

        Args:
            db: Async SQLAlchemy session
        """
        self.db = db

    async def register_provider(
        self,
        tenant_id: UUID,
        name: str,
        provider_type: ProviderType,
        config: dict[str, Any],
        capabilities: dict[str, Any] | None = None,
    ) -> Provider:
        """Register a new provider.

        Args:
            tenant_id: Tenant UUID for multi-tenancy
            name: Provider name
            provider_type: Type of provider (llm, graphify, gitnexus, etc.)
            config: Provider configuration (API keys, endpoints, etc.)
            capabilities: Optional capability definitions

        Returns:
            Created Provider instance

        Raises:
            ValueError: If provider type is invalid
        """
        config = validate_provider_config_boundary(config)

        # Create provider
        provider = Provider(
            tenant_id=tenant_id,
            name=name,
            provider_type=provider_type.value,
            config_json=config,
            capabilities_json=capabilities,
            status=ProviderStatus.ACTIVE.value,
        )
        self.db.add(provider)
        await self.db.flush()
        await self.db.refresh(provider)

        # Create initial version
        await self.create_version(
            provider_id=provider.id,
            config=config,
            capabilities=capabilities,
            set_active=True,
        )

        return provider

    async def get_provider(self, provider_id: UUID, tenant_id: UUID) -> Provider | None:
        """Get a provider by ID with tenant isolation.

        Args:
            provider_id: Provider UUID
            tenant_id: Tenant UUID for access control

        Returns:
            Provider if found and accessible, None otherwise
        """
        result = await self.db.execute(
            select(Provider).where(
                Provider.id == provider_id,
                Provider.tenant_id == tenant_id,
                Provider.deleted_at.is_(None),
            ).options(selectinload(Provider.versions))
        )
        return result.scalar_one_or_none()

    async def list_providers(
        self,
        tenant_id: UUID,
        provider_type: ProviderType | None = None,
        status: ProviderStatus | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Provider], int]:
        """List all providers for a tenant.

        Args:
            tenant_id: Tenant UUID
            provider_type: Optional filter by provider type
            status: Optional filter by status
            skip: Pagination offset
            limit: Page size

        Returns:
            Tuple of (providers list, total count)
        """
        query = select(Provider).where(
            Provider.tenant_id == tenant_id,
            Provider.deleted_at.is_(None),
        )

        if provider_type:
            query = query.where(Provider.provider_type == provider_type.value)

        if status:
            query = query.where(Provider.status == status.value)

        # Get total count
        count_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar() or 0

        # Get paginated results
        query = query.order_by(Provider.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        providers = list(result.scalars().all())

        return providers, total

    async def update_provider_config(
        self,
        provider_id: UUID,
        tenant_id: UUID,
        config: dict[str, Any],
    ) -> Provider | None:
        """Update provider configuration.

        Args:
            provider_id: Provider UUID
            tenant_id: Tenant UUID for access control
            config: New configuration

        Returns:
            Updated Provider if found, None otherwise
        """
        provider = await self.get_provider(provider_id, tenant_id)
        if not provider:
            return None

        config = validate_provider_config_boundary(config)
        provider.config_json = config
        await self.db.flush()
        await self.db.refresh(provider)
        return provider

    async def set_provider_status(
        self,
        provider_id: UUID,
        tenant_id: UUID,
        status: ProviderStatus,
    ) -> Provider | None:
        """Set provider status.

        Args:
            provider_id: Provider UUID
            tenant_id: Tenant UUID for access control
            status: New status

        Returns:
            Updated Provider if found, None otherwise
        """
        provider = await self.get_provider(provider_id, tenant_id)
        if not provider:
            return None

        provider.status = status.value
        await self.db.flush()
        await self.db.refresh(provider)
        return provider

    async def get_active_version(self, provider_id: UUID) -> ProviderVersion | None:
        """Get the currently active version for a provider.

        Args:
            provider_id: Provider UUID

        Returns:
            Active ProviderVersion if exists, None otherwise
        """
        result = await self.db.execute(
            select(ProviderVersion).where(
                ProviderVersion.provider_id == provider_id,
                ProviderVersion.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def create_version(
        self,
        provider_id: UUID,
        config: dict[str, Any],
        capabilities: dict[str, Any] | None = None,
        set_active: bool = True,
    ) -> ProviderVersion:
        """Create a new provider version.

        Args:
            provider_id: Provider UUID
            config: Version configuration
            capabilities: Version capabilities
            set_active: If True, set this as the active version

        Returns:
            Created ProviderVersion
        """
        config = validate_provider_config_boundary(config)

        # Get latest version number
        result = await self.db.execute(
            select(func.max(ProviderVersion.version)).where(
                ProviderVersion.provider_id == provider_id
            )
        )
        latest_version = result.scalar() or "0"
        version_parts = latest_version.split(".")
        major = int(version_parts[0]) if version_parts else 0
        new_version = f"{major + 1}.0"

        # If setting active, deactivate other versions
        if set_active:
            await self.db.execute(
                update(ProviderVersion)
                .where(
                    ProviderVersion.provider_id == provider_id,
                    ProviderVersion.is_active == True,
                )
                .values(is_active=False)
            )

        version = ProviderVersion(
            provider_id=provider_id,
            version=new_version,
            config_json=config,
            capabilities_json=capabilities,
            is_active=set_active,
        )
        self.db.add(version)
        await self.db.flush()
        await self.db.refresh(version)

        # Update provider's current_version_id
        await self.db.execute(
            update(Provider)
            .where(Provider.id == provider_id)
            .values(current_version_id=version.id)
        )

        return version

    async def rollback_to_version(
        self,
        provider_id: UUID,
        tenant_id: UUID,
        version_id: UUID,
    ) -> Provider | None:
        """Rollback provider to a specific version.

        Args:
            provider_id: Provider UUID
            tenant_id: Tenant UUID for access control
            version_id: Version UUID to rollback to

        Returns:
            Updated Provider if successful, None otherwise
        """
        provider = await self.get_provider(provider_id, tenant_id)
        if not provider:
            return None

        # Verify version exists for this provider
        result = await self.db.execute(
            select(ProviderVersion).where(
                ProviderVersion.id == version_id,
                ProviderVersion.provider_id == provider_id,
            )
        )
        version = result.scalar_one_or_none()
        if not version:
            return None

        # Deactivate all versions
        await self.db.execute(
            update(ProviderVersion)
            .where(ProviderVersion.provider_id == provider_id)
            .values(is_active=False)
        )

        # Activate the target version
        version.is_active = True
        provider.current_version_id = version_id
        provider.status = ProviderStatus.ROLLBACK.value

        await self.db.flush()
        await self.db.refresh(provider)
        return provider

    async def record_run(
        self,
        tenant_id: UUID,
        provider_id: UUID,
        version_id: UUID | None,
        capability_type: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
        status: RunStatus = RunStatus.SUCCESS,
        error_message: str | None = None,
    ) -> ProviderRun:
        """Record a provider run.

        Args:
            tenant_id: Tenant UUID
            provider_id: Provider UUID
            version_id: Version UUID
            capability_type: Type of capability invoked
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            latency_ms: Latency in milliseconds
            status: Run status
            error_message: Error message if failed

        Returns:
            Created ProviderRun
        """
        run = ProviderRun(
            tenant_id=tenant_id,
            provider_id=provider_id,
            version_id=version_id,
            capability_type=capability_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            status=status.value,
            error_message=sanitize_error_message(error_message),
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_runs(
        self,
        provider_id: UUID,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[ProviderRun], int]:
        """Get provider run history.

        Args:
            provider_id: Provider UUID
            tenant_id: Tenant UUID for access control
            skip: Pagination offset
            limit: Page size

        Returns:
            Tuple of (runs list, total count)
        """
        query = select(ProviderRun).where(
            ProviderRun.provider_id == provider_id,
            ProviderRun.tenant_id == tenant_id,
        )

        count_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar() or 0

        query = query.order_by(ProviderRun.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        runs = list(result.scalars().all())

        return runs, total

    async def update_health(
        self,
        provider_id: UUID,
        status: HealthStatus,
        response_time_ms: int | None = None,
        success_rate: float | None = None,
    ) -> ProviderHealth:
        """Update provider health record.

        Args:
            provider_id: Provider UUID
            status: Health status
            response_time_ms: Current response time
            success_rate: Current success rate (0-100)

        Returns:
            Created or updated ProviderHealth
        """
        health = ProviderHealth(
            provider_id=provider_id,
            status=status.value,
            response_time_ms=response_time_ms,
            success_rate=success_rate,
            last_check_at=datetime.now(timezone.utc),
        )
        self.db.add(health)
        await self.db.flush()
        await self.db.refresh(health)
        return health

    async def delete_provider(self, provider_id: UUID, tenant_id: UUID) -> bool:
        """Soft delete a provider.

        Args:
            provider_id: Provider UUID
            tenant_id: Tenant UUID for access control

        Returns:
            True if deleted, False if not found
        """
        provider = await self.get_provider(provider_id, tenant_id)
        if not provider:
            return False

        provider.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def get_provider_capabilities(self, provider_id: UUID) -> list[ProviderCapability]:
        """Get all capabilities for a provider.

        Args:
            provider_id: Provider UUID

        Returns:
            List of ProviderCapability objects
        """
        result = await self.db.execute(
            select(ProviderCapability).where(
                ProviderCapability.provider_id == provider_id
            )
        )
        return list(result.scalars().all())
