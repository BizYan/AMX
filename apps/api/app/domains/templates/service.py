"""Template Domain Service

Business logic for template management, versioning, and parsing.
"""

import hashlib
import io
import zipfile
from typing import Any
from uuid import UUID
from xml.etree import ElementTree

from sqlalchemy import delete, select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.placeholders import extract_raw_placeholders, is_valid_placeholder_name
from app.domains.agent.models import AgentSkill
from app.domains.templates.models import Template, TemplateVersion
from app.domains.templates.models import TemplateSection, TemplateSectionSkillBinding
from app.domains.templates.schemas import (
    PlaceholderSchema,
    PageTypeSchema,
    TemplateCreate,
    TemplateUpdate,
    TemplateVersionCreate,
    TemplateUploadRequest,
    TemplateSectionCreate,
    TemplateSectionUpdate,
    ParsedTemplate,
)


class TemplateService:
    """Service for template management operations.

    Handles CRUD operations for templates and versions,
    template parsing, and variable substitution.
    """

    def __init__(self, db: AsyncSession):
        """Initialize template service.

        Args:
            db: Async database session
        """
        self.db = db

    @staticmethod
    def _is_active_value(value: str | None) -> bool:
        """Return whether a stored template active flag should be treated as active."""
        return str(value or "").lower() in {"true", "active", "1", "yes"}

    async def create_template(
        self,
        tenant_id: UUID,
        template_data: TemplateCreate,
        created_by: UUID | None = None,
    ) -> Template:
        """Create a new template.

        Args:
            tenant_id: Tenant UUID
            template_data: Template creation data
            created_by: User ID of creator

        Returns:
            Created Template
        """
        if created_by is None:
            raise ValueError("created_by is required")

        template = Template(
            tenant_id=tenant_id,
            name=template_data.name,
            description=template_data.description,
            doc_type=template_data.doc_type,
            version_count=0,
            is_active="true",
            created_by=created_by,
        )
        self.db.add(template)
        await self.db.flush()
        await self.db.refresh(template)
        return template

    async def get_template(
        self,
        template_id: UUID,
        tenant_id: UUID | None = None,
        include_deleted: bool = False,
    ) -> Template | None:
        """Get template by ID.

        Args:
            template_id: Template UUID
            tenant_id: Optional tenant filter
            include_deleted: Whether to include soft-deleted templates

        Returns:
            Template if found, None otherwise
        """
        query = select(Template).where(Template.id == template_id)
        if not include_deleted:
            query = query.where(Template.deleted_at.is_(None))
        if tenant_id is not None:
            query = query.where(Template.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_template_with_versions(
        self,
        template_id: UUID,
        tenant_id: UUID | None = None,
    ) -> Template | None:
        """Get template by ID with versions loaded.

        Args:
            template_id: Template UUID
            tenant_id: Optional tenant filter

        Returns:
            Template with versions if found, None otherwise
        """
        from sqlalchemy.orm import selectinload

        query = (
            select(Template)
            .options(selectinload(Template.versions))
            .where(Template.id == template_id)
            .where(Template.deleted_at.is_(None))
        )
        if tenant_id is not None:
            query = query.where(Template.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_templates(
        self,
        tenant_id: UUID,
        doc_type: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Template], int]:
        """List templates for a tenant with optional filters.

        Args:
            tenant_id: Tenant UUID
            doc_type: Optional document type filter
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of Templates, total count)
        """
        base_query = select(Template).where(
            Template.tenant_id == tenant_id,
            Template.deleted_at.is_(None),
        )

        if doc_type is not None:
            base_query = base_query.where(Template.doc_type == doc_type)

        # Count total
        count_query = select(func.count(Template.id)).select_from(base_query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get paginated results
        result = await self.db.execute(
            base_query
            .offset(skip)
            .limit(limit)
            .order_by(Template.updated_at.desc())
        )
        templates = list(result.scalars().all())

        return templates, total

    async def update_template(
        self,
        template_id: UUID,
        tenant_id: UUID | None,
        update_data: TemplateUpdate,
    ) -> Template | None:
        """Update a template.

        Args:
            template_id: Template UUID
            tenant_id: Optional tenant filter
            update_data: Update data

        Returns:
            Updated Template if found, None otherwise
        """
        template = await self.get_template(template_id, tenant_id)
        if not template:
            return None

        if update_data.name is not None:
            template.name = update_data.name
        if update_data.description is not None:
            template.description = update_data.description
        if update_data.is_active is not None:
            template.is_active = update_data.is_active

        await self.db.flush()
        await self.db.refresh(template)
        return template

    async def soft_delete_template(
        self,
        template_id: UUID,
        tenant_id: UUID | None,
    ) -> bool:
        """Soft delete a template.

        Args:
            template_id: Template UUID
            tenant_id: Optional tenant filter

        Returns:
            True if deleted, False if not found
        """
        template = await self.get_template(template_id, tenant_id)
        if not template:
            return False

        from datetime import datetime, timezone
        template.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def create_template_version(
        self,
        tenant_id: UUID | None,
        template_id: UUID,
        version_data: TemplateVersionCreate,
        created_by: UUID | None = None,
    ) -> TemplateVersion | None:
        """Create a new version for an existing template.

        Args:
            tenant_id: Optional tenant filter
            template_id: Template UUID
            version_data: Version creation data
            created_by: User ID of creator

        Returns:
            Created TemplateVersion if template found, None otherwise
        """
        if created_by is None:
            raise ValueError("created_by is required")

        template = await self.get_template(template_id, tenant_id)
        if not template:
            return None

        # Calculate file hash if content provided
        file_hash = None
        if version_data.content:
            file_hash = hashlib.sha256(version_data.content).hexdigest()

        # Parse template if content provided
        parsed_placeholders = None
        parsed_page_types = None
        if version_data.content:
            parsed = await self.parse_template(tenant_id, version_data.content, template.doc_type)
            parsed_placeholders = [p.model_dump() for p in parsed.placeholders] if parsed.placeholders else None
            parsed_page_types = [p.model_dump() for p in parsed.page_types] if parsed.page_types else None
        elif version_data.placeholder_schema:
            parsed_placeholders = [p.model_dump() if hasattr(p, 'model_dump') else p for p in version_data.placeholder_schema]

        version_is_active = version_data.is_active or "true"
        if self._is_active_value(version_is_active):
            await self._deactivate_template_versions(template_id, tenant_id)

        # Create new version
        version = TemplateVersion(
            tenant_id=tenant_id,
            template_id=template_id,
            version=version_data.version,
            content=version_data.content,
            file_hash=file_hash or version_data.file_hash,
            placeholder_schema=parsed_placeholders,
            page_types=parsed_page_types,
            is_active=version_is_active,
            created_by=created_by,
        )
        self.db.add(version)

        # Update template version count
        template.version_count = version_data.version

        await self.db.flush()
        await self.db.refresh(version)
        return version

    async def list_template_versions(
        self,
        tenant_id: UUID | None,
        template_id: UUID,
    ) -> list[TemplateVersion]:
        """List all versions of a template.

        Args:
            tenant_id: Optional tenant filter
            template_id: Template UUID

        Returns:
            List of TemplateVersions
        """
        query = select(TemplateVersion).where(
            TemplateVersion.template_id == template_id,
        ).order_by(TemplateVersion.version.desc())
        if tenant_id is not None:
            query = query.where(TemplateVersion.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_template_version(
        self,
        tenant_id: UUID | None,
        template_id: UUID,
        version_id: UUID,
    ) -> TemplateVersion | None:
        """Get a specific version of a template.

        Args:
            tenant_id: Optional tenant filter
            template_id: Template UUID
            version_id: Version UUID

        Returns:
            TemplateVersion if found, None otherwise
        """
        query = select(TemplateVersion).where(
            TemplateVersion.id == version_id,
            TemplateVersion.template_id == template_id,
        )
        if tenant_id is not None:
            query = query.where(TemplateVersion.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def _deactivate_template_versions(
        self,
        template_id: UUID,
        tenant_id: UUID | None,
    ) -> None:
        """Deactivate active versions for a template before selecting a new active version."""
        stmt = (
            update(TemplateVersion)
            .where(TemplateVersion.template_id == template_id)
            .values(is_active="false")
        )
        if tenant_id is not None:
            stmt = stmt.where(TemplateVersion.tenant_id == tenant_id)

        await self.db.execute(stmt)

    async def activate_template_version(
        self,
        tenant_id: UUID | None,
        template_id: UUID,
        version_id: UUID,
    ) -> TemplateVersion | None:
        """Activate an existing template version and deactivate its sibling versions."""
        template = await self.get_template(template_id, tenant_id)
        if not template:
            return None

        version = await self.get_template_version(tenant_id, template_id, version_id)
        if not version:
            return None

        await self._deactivate_template_versions(template_id, tenant_id)
        version.is_active = "true"
        await self.db.flush()
        await self.db.refresh(version)
        return version

    async def upload_template_version(
        self,
        tenant_id: UUID | None,
        template_id: UUID,
        file_content: bytes,
        description: str | None = None,
        created_by: UUID | None = None,
    ) -> TemplateVersion | None:
        """Upload a new template file and create a version.

        Args:
            tenant_id: Optional tenant filter
            template_id: Template UUID
            file_content: New template file content
            description: Optional description of changes
            created_by: User ID of uploader

        Returns:
            Created TemplateVersion if template found, None otherwise
        """
        if created_by is None:
            raise ValueError("created_by is required")

        template = await self.get_template(template_id, tenant_id)
        if not template:
            return None

        # Calculate file hash
        file_hash = hashlib.sha256(file_content).hexdigest()

        # Parse template for placeholders
        parsed = await self.parse_template(tenant_id, file_content, template.doc_type)

        # Determine next version number
        result = await self.db.execute(
            select(func.max(TemplateVersion.version)).where(
                TemplateVersion.template_id == template_id
            )
        )
        max_version = result.scalar() or 0
        new_version_number = max_version + 1

        await self._deactivate_template_versions(template_id, tenant_id)

        # Create new version
        version = TemplateVersion(
            tenant_id=tenant_id,
            template_id=template_id,
            version=new_version_number,
            content=file_content,
            file_hash=file_hash,
            placeholder_schema=[p.model_dump() for p in parsed.placeholders] if parsed.placeholders else None,
            page_types=[p.model_dump() for p in parsed.page_types] if parsed.page_types else None,
            is_active="true",
            created_by=created_by,
        )
        self.db.add(version)

        # Update template version count
        template.version_count = new_version_number

        await self.db.flush()
        await self.db.refresh(version)
        return version

    async def parse_template(
        self,
        tenant_id: UUID | None,
        file_content: bytes,
        doc_type: str,
    ) -> ParsedTemplate:
        """Parse template file content to extract placeholders.

        Args:
            tenant_id: Optional tenant filter
            file_content: Template file content as bytes
            doc_type: Document type hint

        Returns:
            ParsedTemplate with extracted placeholders and page types
        """
        file_hash = hashlib.sha256(file_content).hexdigest()
        placeholders: list[PlaceholderSchema] = []
        page_types: list[PageTypeSchema] = []
        warnings: list[str] = []
        errors: list[str] = []
        invalid_placeholders: list[str] = []
        duplicate_placeholders: list[str] = []

        content_str, content_format, page_types = self._extract_template_text(file_content)
        raw_placeholders = self._extract_raw_placeholders(content_str)
        placeholder_counts: dict[str, int] = {}

        for raw_name in raw_placeholders:
            placeholder_name = raw_name.strip()
            if placeholder_name != raw_name:
                warnings.append(f"占位符包含首尾空格：{{{{{raw_name}}}}}")

            if not self._is_valid_placeholder_name(placeholder_name):
                invalid_placeholders.append(raw_name)
                continue

            placeholder_counts[placeholder_name] = placeholder_counts.get(placeholder_name, 0) + 1

        for name, occurrence_count in sorted(placeholder_counts.items()):
            if occurrence_count > 1:
                duplicate_placeholders.append(name)
            placeholders.append(
                PlaceholderSchema(
                    name=name,
                    description=f"自动提取的占位符：{name}",
                    field_type="text",
                    required=True,
                    occurrence_count=occurrence_count,
                )
            )

        if not placeholders:
            warnings.append("未识别到符合 {{变量名}} 规范的占位符。")

        if invalid_placeholders:
            errors.append("存在不符合命名规范的占位符；请使用中文、英文、数字、下划线、短横线或点号，且不能以数字开头。")

        return ParsedTemplate(
            placeholders=placeholders,
            page_types=page_types,
            file_hash=file_hash,
            total_pages=len(page_types) if page_types else 0,
            is_valid=not errors,
            warnings=warnings,
            errors=errors,
            invalid_placeholders=sorted(set(invalid_placeholders)),
            duplicate_placeholders=duplicate_placeholders,
            content_format=content_format,
        )

    def _extract_template_text(self, content: bytes) -> tuple[str, str, list[PageTypeSchema]]:
        """Extract text and page metadata from text, DOCX, or PPTX-like template bytes."""
        if zipfile.is_zipfile(io.BytesIO(content)):
            return self._extract_text_from_office_zip(content)

        try:
            return content.decode("utf-8"), "text", []
        except UnicodeDecodeError:
            return self._extract_text_from_binary(content), "binary", []

    def _extract_text_from_office_zip(self, content: bytes) -> tuple[str, str, list[PageTypeSchema]]:
        texts: list[str] = []
        page_types: list[PageTypeSchema] = []
        office_format = "office"

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            slide_names = sorted(
                name for name in names
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
            docx_names = [name for name in names if name.startswith("word/") and name.endswith(".xml")]

            if slide_names:
                office_format = "pptx"
                for index, name in enumerate(slide_names, start=1):
                    slide_text = self._extract_text_from_xml_bytes(archive.read(name))
                    texts.append(slide_text)
                    page_types.append(
                        PageTypeSchema(
                            page_number=index,
                            page_type=self._infer_page_type(slide_text, index),
                            title_placeholder=self._first_placeholder_name(slide_text),
                            content_placeholders=self._valid_placeholder_names(slide_text),
                        )
                    )
            elif docx_names:
                office_format = "docx"
                body_names = [name for name in docx_names if name == "word/document.xml"] or docx_names
                for name in body_names:
                    texts.append(self._extract_text_from_xml_bytes(archive.read(name)))
                page_types.append(
                    PageTypeSchema(
                        page_number=1,
                        page_type="document",
                        title_placeholder=self._first_placeholder_name("\n".join(texts)),
                        content_placeholders=self._valid_placeholder_names("\n".join(texts)),
                    )
                )
            else:
                for name in names:
                    if name.endswith(".xml"):
                        texts.append(self._extract_text_from_xml_bytes(archive.read(name)))

        return "\n".join(texts), office_format, page_types

    def _extract_text_from_xml_bytes(self, content: bytes) -> str:
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError:
            return self._extract_text_from_binary(content)

        return " ".join(text.strip() for text in root.itertext() if text and text.strip())

    def _extract_raw_placeholders(self, content: str) -> list[str]:
        return extract_raw_placeholders(content)

    def _valid_placeholder_names(self, content: str) -> list[str]:
        names: list[str] = []
        for raw_name in self._extract_raw_placeholders(content):
            name = raw_name.strip()
            if self._is_valid_placeholder_name(name) and name not in names:
                names.append(name)
        return names

    def _first_placeholder_name(self, content: str) -> str | None:
        names = self._valid_placeholder_names(content)
        return names[0] if names else None

    def _infer_page_type(self, content: str, page_number: int) -> str:
        lowered = content.lower()
        if page_number == 1 or any(keyword in content for keyword in ("封面", "标题", "项目名称")):
            return "title"
        if any(keyword in content for keyword in ("表格", "矩阵", "清单")) or "table" in lowered:
            return "table"
        if any(keyword in content for keyword in ("图表", "指标", "趋势")) or "chart" in lowered:
            return "chart"
        return "content"

    def _is_valid_placeholder_name(self, name: str) -> bool:
        return is_valid_placeholder_name(name)

    def _extract_text_from_binary(self, content: bytes) -> str:
        """Extract readable text from binary file content.

        Args:
            content: Binary file content

        Returns:
            Extracted text string
        """
        # Simple extraction - get readable ASCII characters
        text = ""
        for byte in content:
            if 32 <= byte <= 126 or byte in (9, 10, 13):
                text += chr(byte)
            else:
                text += " "
        return text

    async def get_active_version(
        self,
        template_id: UUID,
        tenant_id: UUID | None = None,
    ) -> TemplateVersion | None:
        """Get the currently active version of a template.

        Args:
            template_id: Template UUID
            tenant_id: Optional tenant filter

        Returns:
            Active TemplateVersion if found, None otherwise
        """
        query = select(TemplateVersion).where(
            TemplateVersion.template_id == template_id,
            TemplateVersion.is_active.in_(("true", "active", "1", "yes")),
        )
        if tenant_id is not None:
            query = query.where(TemplateVersion.tenant_id == tenant_id)

        result = await self.db.execute(
            query.order_by(TemplateVersion.version.desc()).limit(1)
        )
        return result.scalars().first()

    async def get_version(
        self,
        version_id: UUID,
        tenant_id: UUID | None = None,
    ) -> TemplateVersion | None:
        """Get a specific template version.

        Args:
            version_id: TemplateVersion UUID
            tenant_id: Optional tenant filter

        Returns:
            TemplateVersion if found, None otherwise
        """
        query = select(TemplateVersion).where(TemplateVersion.id == version_id)
        if tenant_id is not None:
            query = query.where(TemplateVersion.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def substitute_variables(
        self,
        content: str,
        variables: dict[str, Any],
    ) -> str:
        """Substitute variables in content with provided values.

        Args:
            content: Content containing {{variable}} placeholders
            variables: Dictionary mapping variable names to values

        Returns:
            Content with variables substituted
        """
        result = content
        for var_name, value in variables.items():
            placeholder = "{{" + var_name + "}}"
            result = result.replace(placeholder, str(value))
        return result


class TemplateSectionService:
    """Service for structured template sections and section skill bindings."""

    STANDARD_SECTIONS: dict[str, list[dict[str, Any]]] = {
        "urs": [
            {
                "section_key": "urs.business-vision",
                "title": "业务愿景",
                "content_requirement": "说明业务背景、目标用户、核心痛点和项目成功标准。",
                "prompt": "请基于项目资料生成 URS 业务愿景，保持咨询交付语言清晰、可审计。",
                "required_inputs": ["project_background", "stakeholders"],
                "quality_rules": [{"rule": "必须说明业务目标和成功口径", "severity": "high"}],
            },
            {
                "section_key": "urs.user-needs",
                "title": "用户需求",
                "content_requirement": "列出用户角色、业务场景和用户目标。",
                "prompt": "请按用户角色和业务场景整理 URS 用户需求。",
                "required_inputs": ["user_roles", "business_scenarios"],
                "quality_rules": [{"rule": "每项需求必须能追溯到用户或场景", "severity": "high"}],
            },
            {
                "section_key": "urs.acceptance",
                "title": "验收标准",
                "content_requirement": "定义可验证的验收标准和评审口径。",
                "prompt": "请为每项用户需求生成可验证的验收标准。",
                "required_inputs": ["requirements"],
                "quality_rules": [{"rule": "验收标准必须可测试", "severity": "high"}],
            },
        ],
        "brd": [
            {
                "section_key": "brd.context",
                "title": "业务背景",
                "content_requirement": "说明业务现状、关键流程和改进机会。",
                "prompt": "请生成 BRD 业务背景，突出业务价值和流程约束。",
                "required_inputs": ["business_context", "process_notes"],
                "quality_rules": [{"rule": "必须包含业务价值", "severity": "medium"}],
            },
            {
                "section_key": "brd.capabilities",
                "title": "业务能力",
                "content_requirement": "定义目标业务能力、边界和依赖。",
                "prompt": "请用业务能力视角组织 BRD 目标能力。",
                "required_inputs": ["capability_map"],
                "quality_rules": [{"rule": "能力必须有边界说明", "severity": "high"}],
            },
            {
                "section_key": "brd.risks",
                "title": "业务风险",
                "content_requirement": "列出主要业务风险、影响和缓解建议。",
                "prompt": "请识别 BRD 业务风险并给出缓解建议。",
                "required_inputs": ["risk_notes"],
                "quality_rules": [{"rule": "风险必须包含影响说明", "severity": "medium"}],
            },
        ],
        "prd": [
            {
                "section_key": "prd.overview",
                "title": "产品概述",
                "content_requirement": "说明产品目标、用户对象、核心价值和成功指标。",
                "prompt": "请生成 PRD 产品概述，保留产品目标、用户对象和成功指标。",
                "required_inputs": ["product_goal", "target_users"],
                "quality_rules": [{"rule": "必须明确产品目标", "severity": "high"}],
            },
            {
                "section_key": "prd.goals",
                "title": "目标与指标",
                "content_requirement": "定义业务目标、产品指标和验收口径。",
                "prompt": "请将 PRD 目标拆解为可衡量指标。",
                "required_inputs": ["business_goals", "metrics"],
                "quality_rules": [{"rule": "指标必须可衡量", "severity": "high"}],
            },
            {
                "section_key": "prd.scope",
                "title": "范围与边界",
                "content_requirement": "说明本期范围、非目标和关键依赖。",
                "prompt": "请整理 PRD 范围、非目标和依赖关系。",
                "required_inputs": ["scope", "out_of_scope", "dependencies"],
                "quality_rules": [{"rule": "必须说明非目标", "severity": "medium"}],
            },
            {
                "section_key": "prd.requirements",
                "title": "功能需求",
                "content_requirement": "按用户旅程和业务规则描述功能需求、状态和异常路径。",
                "prompt": "请生成 PRD 功能需求，逐项包含用户价值、业务规则和验收标准。",
                "required_inputs": ["user_personas", "user_journeys", "business_rules"],
                "quality_rules": [{"rule": "每条需求必须包含验收标准", "severity": "high"}],
            },
            {
                "section_key": "prd.metrics",
                "title": "发布与度量",
                "content_requirement": "定义发布条件、观测指标和上线后验证计划。",
                "prompt": "请生成 PRD 发布与度量章节，确保上线条件可审计。",
                "required_inputs": ["release_plan", "measurement_plan"],
                "quality_rules": [{"rule": "必须包含上线后验证计划", "severity": "medium"}],
            },
        ],
        "test_case": [
            {
                "section_key": "test_case.scope",
                "title": "测试范围",
                "content_requirement": "说明被测范围、排除范围和环境假设。",
                "prompt": "请生成测试用例测试范围，明确边界和环境。",
                "required_inputs": ["requirements", "environment"],
                "quality_rules": [{"rule": "必须绑定需求来源", "severity": "high"}],
            },
            {
                "section_key": "test_case.cases",
                "title": "测试用例",
                "content_requirement": "列出前置条件、步骤、预期结果和优先级。",
                "prompt": "请按可执行测试用例格式生成测试步骤。",
                "required_inputs": ["acceptance_criteria"],
                "quality_rules": [{"rule": "每个用例必须有预期结果", "severity": "high"}],
            },
        ],
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_template_sections(
        self,
        tenant_id: UUID,
        template_id: UUID,
        version_id: UUID | None = None,
    ) -> list[TemplateSection]:
        """List structured sections for a template version."""
        query = (
            select(TemplateSection)
            .join(TemplateVersion, TemplateVersion.id == TemplateSection.template_version_id)
            .options(
                selectinload(TemplateSection.skill_bindings).selectinload(
                    TemplateSectionSkillBinding.skill
                )
            )
            .where(
                TemplateVersion.template_id == template_id,
                TemplateSection.tenant_id == tenant_id,
                TemplateSection.deleted_at.is_(None),
            )
            .order_by(TemplateSection.position, TemplateSection.section_key)
        )
        if version_id is not None:
            query = query.where(TemplateSection.template_version_id == version_id)

        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def get_active_template_version(
        self,
        tenant_id: UUID,
        template_id: UUID,
    ) -> TemplateVersion | None:
        """Return the active or latest version for a template."""
        result = await self.db.execute(
            select(TemplateVersion)
            .where(
                TemplateVersion.tenant_id == tenant_id,
                TemplateVersion.template_id == template_id,
            )
            .order_by(TemplateVersion.is_active.desc(), TemplateVersion.version.desc())
        )
        return result.scalars().first()

    async def seed_standard_sections(
        self,
        tenant_id: UUID,
        template_version_id: UUID,
        doc_type: str,
        created_by: UUID,
    ) -> list[TemplateSection]:
        """Seed the standard section structure for a document type."""
        version = await self._get_template_version(tenant_id, template_version_id)
        if not version:
            raise ValueError("Template version not found")

        existing = await self._list_sections_for_version(tenant_id, template_version_id)
        if existing:
            return existing

        sections: list[TemplateSection] = []
        for position, spec in enumerate(self.STANDARD_SECTIONS.get(doc_type, self.STANDARD_SECTIONS["urs"])):
            section = TemplateSection(
                tenant_id=tenant_id,
                template_version_id=template_version_id,
                parent_section_id=None,
                section_key=spec["section_key"],
                title=spec["title"],
                level=1,
                position=position,
                content_requirement=spec["content_requirement"],
                prompt=spec["prompt"],
                required_inputs=spec["required_inputs"],
                quality_rules=spec["quality_rules"],
                created_by=created_by,
            )
            self.db.add(section)
            sections.append(section)

        await self.db.flush()
        for section in sections:
            await self.db.refresh(section)
        return sections

    async def create_template_section(
        self,
        tenant_id: UUID,
        template_version_id: UUID,
        data: TemplateSectionCreate,
        created_by: UUID,
    ) -> TemplateSection:
        """Create a section inside one template version."""
        version = await self._get_template_version(tenant_id, template_version_id)
        if not version:
            raise ValueError("Template version not found")

        if data.parent_section_id:
            parent = await self._get_section(tenant_id, data.parent_section_id)
            if not parent or parent.template_version_id != template_version_id:
                raise ValueError("Parent section not found in template version")

        section = TemplateSection(
            tenant_id=tenant_id,
            template_version_id=template_version_id,
            parent_section_id=data.parent_section_id,
            section_key=data.section_key,
            title=data.title,
            level=data.level,
            position=data.position,
            content_requirement=data.content_requirement,
            prompt=data.prompt,
            required_inputs=data.required_inputs,
            quality_rules=data.quality_rules,
            created_by=created_by,
        )
        self.db.add(section)
        await self.db.flush()
        await self.db.refresh(section)
        return section

    async def update_template_section(
        self,
        tenant_id: UUID,
        section_id: UUID,
        data: TemplateSectionUpdate,
    ) -> TemplateSection | None:
        """Update a template section."""
        section = await self._get_section(tenant_id, section_id)
        if not section:
            return None

        updates = data.model_dump(exclude_unset=True)
        if updates.get("parent_section_id"):
            parent = await self._get_section(tenant_id, updates["parent_section_id"])
            if not parent or parent.template_version_id != section.template_version_id:
                raise ValueError("Parent section not found in template version")

        for field, value in updates.items():
            setattr(section, field, value)

        await self.db.flush()
        await self.db.refresh(section)
        return section

    async def delete_template_section(
        self,
        tenant_id: UUID,
        section_id: UUID,
    ) -> bool:
        """Soft delete a template section and remove its skill bindings."""
        section = await self._get_section(tenant_id, section_id)
        if not section:
            return False

        from datetime import datetime, timezone

        await self.db.execute(
            delete(TemplateSectionSkillBinding).where(
                TemplateSectionSkillBinding.section_id == section_id
            )
        )
        section.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def replace_section_skill_bindings(
        self,
        tenant_id: UUID,
        section_id: UUID,
        skill_ids: list[UUID],
        created_by: UUID,
    ) -> list[TemplateSectionSkillBinding]:
        """Replace the ordered skill bindings for a section."""
        section = await self._get_section(tenant_id, section_id)
        if not section:
            raise ValueError("Template section not found")

        await self._validate_skill_ids(tenant_id, skill_ids)
        await self.db.execute(
            delete(TemplateSectionSkillBinding).where(
                TemplateSectionSkillBinding.section_id == section_id
            )
        )

        for order_index, skill_id in enumerate(skill_ids):
            self.db.add(
                TemplateSectionSkillBinding(
                    tenant_id=tenant_id,
                    section_id=section_id,
                    skill_id=skill_id,
                    order_index=order_index,
                    is_required=1,
                    created_by=created_by,
                )
            )

        await self.db.flush()
        result = await self.db.execute(
            select(TemplateSectionSkillBinding)
            .options(selectinload(TemplateSectionSkillBinding.skill))
            .where(TemplateSectionSkillBinding.section_id == section_id)
            .order_by(TemplateSectionSkillBinding.order_index)
        )
        return list(result.scalars().unique().all())

    async def _get_template_version(
        self,
        tenant_id: UUID,
        template_version_id: UUID,
    ) -> TemplateVersion | None:
        result = await self.db.execute(
            select(TemplateVersion).where(
                TemplateVersion.id == template_version_id,
                TemplateVersion.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_section(
        self,
        tenant_id: UUID,
        section_id: UUID,
    ) -> TemplateSection | None:
        result = await self.db.execute(
            select(TemplateSection)
            .options(
                selectinload(TemplateSection.skill_bindings).selectinload(
                    TemplateSectionSkillBinding.skill
                )
            )
            .where(
                TemplateSection.id == section_id,
                TemplateSection.tenant_id == tenant_id,
                TemplateSection.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def _list_sections_for_version(
        self,
        tenant_id: UUID,
        template_version_id: UUID,
    ) -> list[TemplateSection]:
        result = await self.db.execute(
            select(TemplateSection)
            .where(
                TemplateSection.tenant_id == tenant_id,
                TemplateSection.template_version_id == template_version_id,
                TemplateSection.deleted_at.is_(None),
            )
            .order_by(TemplateSection.position, TemplateSection.section_key)
        )
        return list(result.scalars().all())

    async def _validate_skill_ids(
        self,
        tenant_id: UUID,
        skill_ids: list[UUID],
    ) -> None:
        for skill_id in skill_ids:
            result = await self.db.execute(
                select(AgentSkill).where(
                    AgentSkill.id == skill_id,
                    AgentSkill.tenant_id == tenant_id,
                    AgentSkill.deleted_at.is_(None),
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError("Skill does not belong to tenant")
