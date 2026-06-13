"""Tests for template service upload and parsing behavior."""

import os
import io
import zipfile
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-secret"

import pytest

from app.core.settings import settings
from app.domains.templates.service import TemplateService


def _pptx_fixture(slide_texts: list[str]) -> bytes:
    """Create the smallest ZIP shape needed by the template parser."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index, text in enumerate(slide_texts, start=1):
            archive.writestr(
                f"ppt/slides/slide{index}.xml",
                f"<p:sld xmlns:p='p' xmlns:a='a'><p:cSld><p:spTree><a:t>{text}</a:t></p:spTree></p:cSld></p:sld>",
            )
    return buffer.getvalue()

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]


class MaxVersionResult:
    def scalar(self):
        return 2


class ActiveVersionResult:
    def __init__(self, version):
        self.version = version

    def scalars(self):
        return self

    def first(self):
        return self.version


@pytest.mark.asyncio
async def test_upload_template_version_passes_tenant_context_to_parser():
    tenant_id = uuid4()
    template_id = uuid4()
    created_by = uuid4()
    file_content = b"# Template\nProject: {{project_name}}"

    db = AsyncMock()
    db.execute.return_value = MaxVersionResult()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    template = MagicMock()
    template.doc_type = "urs"
    template.version_count = 0

    service = TemplateService(db)
    service.get_template = AsyncMock(return_value=template)

    version = await service.upload_template_version(
        tenant_id=tenant_id,
        template_id=template_id,
        file_content=file_content,
        description="Initial version",
        created_by=created_by,
    )

    assert version is not None
    assert version.tenant_id == tenant_id
    assert version.template_id == template_id
    assert version.version == 3
    assert version.created_by == created_by
    assert template.version_count == 3
    assert any(
        placeholder["name"] == "project_name"
        for placeholder in (version.placeholder_schema or [])
    )
    service.get_template.assert_awaited_once_with(template_id, tenant_id)
    db.add.assert_called_once_with(version)
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(version)


@pytest.mark.asyncio
async def test_upload_template_version_deactivates_existing_versions_before_new_active_version():
    tenant_id = uuid4()
    template_id = uuid4()
    file_content = b"# Template\nProject: {{project_name}}"

    db = AsyncMock()
    db.execute.return_value = MaxVersionResult()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    template = MagicMock()
    template.doc_type = "urs"
    template.version_count = 0

    service = TemplateService(db)
    service.get_template = AsyncMock(return_value=template)
    service._deactivate_template_versions = AsyncMock()

    version = await service.upload_template_version(
        tenant_id=tenant_id,
        template_id=template_id,
        file_content=file_content,
        description="Initial version",
    )

    assert version is not None
    assert version.is_active == "true"
    service._deactivate_template_versions.assert_awaited_once_with(template_id, tenant_id)


@pytest.mark.asyncio
async def test_activate_template_version_deactivates_siblings_and_marks_selected_version_active():
    tenant_id = uuid4()
    template_id = uuid4()
    version_id = uuid4()

    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    selected_version = MagicMock()
    selected_version.is_active = "false"

    service = TemplateService(db)
    service.get_template = AsyncMock(return_value=MagicMock())
    service.get_template_version = AsyncMock(return_value=selected_version)
    service._deactivate_template_versions = AsyncMock()

    activated = await service.activate_template_version(
        tenant_id=tenant_id,
        template_id=template_id,
        version_id=version_id,
    )

    assert activated is selected_version
    assert selected_version.is_active == "true"
    service.get_template.assert_awaited_once_with(template_id, tenant_id)
    service.get_template_version.assert_awaited_once_with(tenant_id, template_id, version_id)
    service._deactivate_template_versions.assert_awaited_once_with(template_id, tenant_id)
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(selected_version)


@pytest.mark.asyncio
async def test_get_active_version_returns_first_ordered_active_version_without_requiring_uniqueness():
    tenant_id = uuid4()
    template_id = uuid4()
    active_version = MagicMock()

    db = AsyncMock()
    db.execute.return_value = ActiveVersionResult(active_version)

    service = TemplateService(db)

    result = await service.get_active_version(template_id=template_id, tenant_id=tenant_id)

    assert result is active_version


@pytest.mark.asyncio
async def test_parse_template_supports_chinese_placeholders_and_quality_evidence():
    service = TemplateService(AsyncMock())
    content = "项目：{{项目名称}}\n客户：{{客户名称}}\n重复：{{客户名称}}\n非法：{{ 客户 名称 }}"

    parsed = await service.parse_template(
        tenant_id=uuid4(),
        file_content=content.encode("utf-8"),
        doc_type="brd",
    )

    assert parsed.content_format == "text"
    assert parsed.is_valid is False
    assert [placeholder.name for placeholder in parsed.placeholders] == ["客户名称", "项目名称"]
    assert next(p for p in parsed.placeholders if p.name == "客户名称").occurrence_count == 2
    assert parsed.duplicate_placeholders == ["客户名称"]
    assert parsed.invalid_placeholders == [" 客户 名称 "]
    assert "命名规范" in parsed.errors[0]


@pytest.mark.asyncio
async def test_parse_template_extracts_pptx_slide_placeholders_and_page_types():
    service = TemplateService(AsyncMock())
    content = _pptx_fixture([
        "封面 {{项目名称}} {{客户名称}}",
        "需求矩阵 {{需求矩阵表}} {{验收标准}}",
    ])

    parsed = await service.parse_template(
        tenant_id=uuid4(),
        file_content=content,
        doc_type="prd",
    )

    assert parsed.is_valid is True
    assert parsed.content_format == "pptx"
    assert parsed.total_pages == 2
    assert [page.page_type for page in parsed.page_types] == ["title", "table"]
    assert parsed.page_types[0].title_placeholder == "项目名称"
    assert parsed.page_types[1].content_placeholders == ["需求矩阵表", "验收标准"]
    assert {placeholder.name for placeholder in parsed.placeholders} == {
        "项目名称",
        "客户名称",
        "需求矩阵表",
        "验收标准",
    }
