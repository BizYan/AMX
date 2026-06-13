"""Config Domain Service

Business logic for ConfigUnit management.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.config.models import ConfigUnit
from app.domains.config.schemas import (
    ConfigUnitCreate,
    ConfigUnitUpdate,
    ConfigUnitTestRequest,
)


class ConfigUnitService:
    """Service for ConfigUnit management.

    Handles CRUD operations for document configuration units,
    including versioning and testing.
    """

    def __init__(self, db: AsyncSession):
        """Initialize config unit service.

        Args:
            db: Async database session
        """
        self.db = db

    async def create_config_unit(
        self,
        tenant_id: UUID,
        name: str,
        doc_type: str,
        entity_schema: dict[str, Any] | None = None,
        document_structure: dict[str, Any] | None = None,
        generation_prompt: dict[str, Any] | None = None,
        quality_rules: dict[str, Any] | None = None,
        bound_skills: list[str] | None = None,
        node_flow: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> ConfigUnit:
        """Create a new ConfigUnit.

        Args:
            tenant_id: Tenant UUID
            name: ConfigUnit name
            doc_type: Document type (urs/brd/prd/story/etc)
            entity_schema: JSON Schema for entity validation
            document_structure: Chapter structure definition
            generation_prompt: Prompt rules for generation
            quality_rules: Quality check rules
            bound_skills: List of skill IDs
            node_flow: Node flow configuration
            description: Optional description

        Returns:
            Created ConfigUnit
        """
        config_unit = ConfigUnit(
            tenant_id=tenant_id,
            name=name,
            doc_type=doc_type,
            description=description,
            entity_schema=entity_schema or {},
            document_structure=document_structure or {},
            generation_prompt=generation_prompt or {},
            quality_rules=quality_rules or {},
            bound_skills=bound_skills or [],
            node_flow=node_flow or {
                "stages": ["generate", "review", "confirm", "export"],
                "transitions": {
                    "generate": "review",
                    "review": "confirm",
                    "confirm": "export",
                },
            },
            is_active=False,
            version=1,
        )
        self.db.add(config_unit)
        await self.db.flush()
        await self.db.refresh(config_unit)
        return config_unit

    async def get_config_unit(
        self,
        config_unit_id: UUID,
        tenant_id: UUID,
    ) -> ConfigUnit | None:
        """Get a ConfigUnit by ID.

        Args:
            config_unit_id: ConfigUnit UUID
            tenant_id: Tenant UUID for verification

        Returns:
            ConfigUnit if found, None otherwise
        """
        result = await self.db.execute(
            select(ConfigUnit).where(
                ConfigUnit.id == config_unit_id,
                ConfigUnit.tenant_id == tenant_id,
                ConfigUnit.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_config_units(
        self,
        tenant_id: UUID,
        doc_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
        include_inactive: bool = False,
    ) -> tuple[list[ConfigUnit], int]:
        """List ConfigUnits with pagination.

        Args:
            tenant_id: Tenant UUID
            doc_type: Optional document type filter
            page: Page number (1-indexed)
            page_size: Items per page
            include_inactive: Whether to include inactive units

        Returns:
            Tuple of (list of ConfigUnits, total count)
        """
        # Build base query
        query = select(ConfigUnit).where(
            ConfigUnit.tenant_id == tenant_id,
            ConfigUnit.deleted_at.is_(None),
        )

        if not include_inactive:
            query = query.where(ConfigUnit.is_active == True)  # noqa: E712

        if doc_type:
            query = query.where(ConfigUnit.doc_type == doc_type)

        # Count total
        count_query = select(func.count(ConfigUnit.id)).where(
            ConfigUnit.tenant_id == tenant_id,
            ConfigUnit.deleted_at.is_(None),
        )
        if not include_inactive:
            count_query = count_query.where(ConfigUnit.is_active == True)  # noqa: E712
        if doc_type:
            count_query = count_query.where(ConfigUnit.doc_type == doc_type)

        count_result = await self.db.execute(count_query)
        total = count_result.scalar_one()

        # Get paginated results
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size).order_by(ConfigUnit.created_at.desc())

        result = await self.db.execute(query)
        config_units = list(result.scalars().all())

        return config_units, total

    async def update_config_unit(
        self,
        config_unit_id: UUID,
        tenant_id: UUID,
        updates: ConfigUnitUpdate,
    ) -> ConfigUnit | None:
        """Update a ConfigUnit.

        Args:
            config_unit_id: ConfigUnit UUID
            tenant_id: Tenant UUID for verification
            updates: Update data

        Returns:
            Updated ConfigUnit if found, None otherwise
        """
        result = await self.db.execute(
            select(ConfigUnit).where(
                ConfigUnit.id == config_unit_id,
                ConfigUnit.tenant_id == tenant_id,
                ConfigUnit.deleted_at.is_(None),
            )
        )
        config_unit = result.scalar_one_or_none()

        if not config_unit:
            return None

        # Update fields
        if updates.name is not None:
            config_unit.name = updates.name

        if updates.description is not None:
            config_unit.description = updates.description

        if updates.entity_schema is not None:
            config_unit.entity_schema = updates.entity_schema

        if updates.document_structure is not None:
            config_unit.document_structure = updates.document_structure

        if updates.generation_prompt is not None:
            config_unit.generation_prompt = updates.generation_prompt

        if updates.quality_rules is not None:
            config_unit.quality_rules = updates.quality_rules

        if updates.bound_skills is not None:
            config_unit.bound_skills = updates.bound_skills

        if updates.node_flow is not None:
            config_unit.node_flow = updates.node_flow

        if updates.is_active is not None and not updates.is_active:
            # Deactivating - allow only if currently active
            if config_unit.is_active:
                config_unit.is_active = False

        await self.db.flush()
        await self.db.refresh(config_unit)
        return config_unit

    async def publish_config_unit(
        self,
        config_unit_id: UUID,
        tenant_id: UUID,
        released_by: UUID,
    ) -> ConfigUnit | None:
        """Publish a ConfigUnit (set is_active=True and bump version).

        Args:
            config_unit_id: ConfigUnit UUID
            tenant_id: Tenant UUID for verification
            released_by: User UUID who published

        Returns:
            Published ConfigUnit if found, None otherwise
        """
        result = await self.db.execute(
            select(ConfigUnit).where(
                ConfigUnit.id == config_unit_id,
                ConfigUnit.tenant_id == tenant_id,
                ConfigUnit.deleted_at.is_(None),
            )
        )
        config_unit = result.scalar_one_or_none()

        if not config_unit:
            return None

        # Bump version and activate
        config_unit.version += 1
        config_unit.is_active = True
        config_unit.released_at = datetime.now(timezone.utc)
        config_unit.released_by = released_by

        await self.db.flush()
        await self.db.refresh(config_unit)
        return config_unit

    async def test_config_unit(
        self,
        config_unit_id: UUID,
        tenant_id: UUID,
        test_data: dict[str, Any],
        mode: str = "validate",
    ) -> dict[str, Any]:
        """Test a ConfigUnit in sandbox mode.

        Args:
            config_unit_id: ConfigUnit UUID
            tenant_id: Tenant UUID for verification
            test_data: Test input data
            mode: Test mode ("validate" or "generate")

        Returns:
            Test results with success status, output, errors, and quality score
        """
        result = await self.db.execute(
            select(ConfigUnit).where(
                ConfigUnit.id == config_unit_id,
                ConfigUnit.tenant_id == tenant_id,
                ConfigUnit.deleted_at.is_(None),
            )
        )
        config_unit = result.scalar_one_or_none()

        if not config_unit:
            return {
                "success": False,
                "output": None,
                "errors": [f"ConfigUnit {config_unit_id} not found"],
                "quality_score": None,
            }

        errors = []
        output = None
        quality_score = None

        # Validate entity_schema
        if not isinstance(config_unit.entity_schema, dict):
            errors.append("entity_schema must be a dict")

        # Validate document_structure
        if not isinstance(config_unit.document_structure, dict):
            errors.append("document_structure must be a dict")

        # Validate generation_prompt
        if not isinstance(config_unit.generation_prompt, dict):
            errors.append("generation_prompt must be a dict")

        # Validate quality_rules
        if not isinstance(config_unit.quality_rules, dict):
            errors.append("quality_rules must be a dict")

        # Validate bound_skills
        if not isinstance(config_unit.bound_skills, list):
            errors.append("bound_skills must be a list")

        # Validate node_flow
        if not isinstance(config_unit.node_flow, dict):
            errors.append("node_flow must be a dict")

        if mode == "validate":
            # Just validate the structure
            if not errors:
                output = {
                    "validated": True,
                    "schema_valid": True,
                    "structure_valid": True,
                    "prompt_valid": True,
                    "rules_valid": True,
                }
        elif mode == "generate":
            # Simulate generation test
            if not errors:
                output = {
                    "generated": True,
                    "test_data_received": bool(test_data),
                    "entity_schema_applied": bool(config_unit.entity_schema),
                    "structure_applied": bool(config_unit.document_structure),
                }
                # Simple quality estimation
                quality_score = 0.85

        if errors:
            return {
                "success": False,
                "output": None,
                "errors": errors,
                "quality_score": None,
            }

        return {
            "success": True,
            "output": output,
            "errors": [],
            "quality_score": quality_score,
        }

    async def delete_config_unit(
        self,
        config_unit_id: UUID,
        tenant_id: UUID,
    ) -> bool:
        """Soft delete a ConfigUnit.

        Args:
            config_unit_id: ConfigUnit UUID
            tenant_id: Tenant UUID for verification

        Returns:
            True if deleted, False if not found
        """
        result = await self.db.execute(
            select(ConfigUnit).where(
                ConfigUnit.id == config_unit_id,
                ConfigUnit.tenant_id == tenant_id,
                ConfigUnit.deleted_at.is_(None),
            )
        )
        config_unit = result.scalar_one_or_none()

        if not config_unit:
            return False

        from datetime import datetime, timezone
        config_unit.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True