"""Tests for document lifecycle service behavior."""

from unittest.mock import AsyncMock
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.domains.documents.models import DocumentVersion
from app.domains.documents.service import DocumentGenerationService, DocumentService


@pytest.mark.asyncio
async def test_create_version_persists_submitted_content_and_summary():
    """Saving an edited document should create a baselineable version of the new content."""
    document_id = UUID("12345678-1234-1234-1234-123456789012")
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    user_id = UUID("11111111-1111-1111-1111-111111111111")

    existing_document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        content="old content",
        version=1,
        created_by=user_id,
    )

    db = AsyncMock()
    added_items = []
    db.add = lambda item: added_items.append(item)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    service = DocumentService(db)
    service.get_document = AsyncMock(return_value=existing_document)

    version = await service.create_version(
        document_id=document_id,
        tenant_id=tenant_id,
        content="new content",
        changes_summary="Add review requirements",
        created_by=user_id,
    )

    assert isinstance(version, DocumentVersion)
    assert version in added_items
    assert version.version == 2
    assert version.content == "new content"
    assert version.changes_summary == "Add review requirements"
    assert existing_document.content == "new content"
    assert existing_document.version == 2


@pytest.mark.asyncio
async def test_generate_from_template_substitutes_chinese_placeholders_and_records_unresolved(monkeypatch):
    """Template generation should use the same Chinese placeholder contract as export."""
    tenant_id = uuid4()
    project_id = uuid4()
    template_id = uuid4()
    user_id = uuid4()

    class FakeTemplateService:
        def __init__(self, db):
            self.db = db

        async def get_template(self, requested_template_id, requested_tenant_id):
            assert requested_template_id == template_id
            assert requested_tenant_id == tenant_id
            return SimpleNamespace(id=template_id)

        async def get_active_version(self, requested_template_id):
            assert requested_template_id == template_id
            return SimpleNamespace(
                version=7,
                content=(
                    "# {{项目名称}}\n"
                    "客户：{{客户名称}}\n"
                    "范围：{{业务范围}}\n"
                    "项目别名：${project_name}\n"
                    "生成：[生成时间]\n"
                    "待补：{{验收负责人}}\n"
                ),
            )

    async def fake_create_document(self, **kwargs):
        return SimpleNamespace(
            id=uuid4(),
            content=kwargs["content"],
            metadata_json=kwargs["metadata"],
            doc_type=kwargs["doc_type"],
            title=kwargs["title"],
        )

    monkeypatch.setattr("app.domains.templates.service.TemplateService", FakeTemplateService)
    monkeypatch.setattr(DocumentService, "create_document", fake_create_document)

    service = DocumentGenerationService(AsyncMock(), llm_gateway=None)
    service._get_llm_gateway = lambda: None
    document = await service.generate_from_template(
        doc_type="brd",
        template_id=template_id,
        project_id=project_id,
        tenant_id=tenant_id,
        context={
            "项目名称": "智能仓储一期",
            "客户名称": "远大客户",
            "业务范围": "入库、出库、盘点",
            "title": "BRD 模板生成",
        },
        created_by=user_id,
    )

    assert "# 智能仓储一期" in document.content
    assert "客户：远大客户" in document.content
    assert "范围：入库、出库、盘点" in document.content
    assert "项目别名：智能仓储一期" in document.content
    assert "待补：{{验收负责人}}" in document.content
    assert document.metadata_json["generation_status"] == "placeholder"
    assert document.metadata_json["template_version"] == 7
    assert document.metadata_json["unresolved_template_placeholders"] == ["验收负责人"]
    assert document.metadata_json["template_placeholder_evidence"]["filled_placeholders"] == [
        "业务范围",
        "客户名称",
        "项目名称",
    ]
