"""Tests for production document generation evidence and delivery gates."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domains.documents.schemas import DocumentStatusUpdate
from app.domains.documents.service import DocumentGenerationService, DocumentService
from app.domains.providers.contracts import LLMResponse
from app.domains.projects.lifecycle import default_document_lifecycle_policy


@pytest.mark.asyncio
async def test_generate_document_records_llm_production_evidence(monkeypatch):
    tenant_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()

    class FakeLLM:
        providers = [SimpleNamespace(name="live-minimax", model="MiniMax-Text-01", is_primary=True)]

        async def generate(self, prompt, params):
            assert "Launch Project" in prompt
            return LLMResponse(
                text="# Launch BRD\n\nGenerated from real provider.",
                model="MiniMax-Text-01",
                usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                finish_reason="stop",
                raw_response={"id": "provider-response-1"},
            )

    async def fake_create_document(self, **kwargs):
        return SimpleNamespace(
            id=uuid4(),
            content=kwargs["content"],
            metadata_json=kwargs["metadata"],
            doc_type=kwargs["doc_type"],
            title=kwargs["title"],
        )

    monkeypatch.setattr(DocumentService, "create_document", fake_create_document)

    service = DocumentGenerationService(AsyncMock(), llm_gateway=FakeLLM())
    document = await service.generate_document(
        doc_type="brd",
        project_id=project_id,
        tenant_id=tenant_id,
        context={"title": "Launch Project", "project_name": "Launch Project"},
        created_by=user_id,
    )

    evidence = document.metadata_json["generation_evidence"]
    assert document.metadata_json["generation_status"] == "generated"
    assert evidence["status"] == "generated"
    assert evidence["provider"] == "live-minimax"
    assert evidence["model"] == "MiniMax-Text-01"
    assert evidence["usage"]["total_tokens"] == 18
    assert evidence["latency_ms"] >= 0
    assert len(evidence["prompt_sha256"]) == 64
    assert evidence["finish_reason"] == "stop"
    assert evidence["generated_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("generation_status", ["placeholder", "failed", "partial"])
async def test_formal_delivery_blocks_non_generated_ai_documents(generation_status):
    document = SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        tenant_id=uuid4(),
        status="draft",
        content="# Draft\n\nIncomplete.",
        metadata_json={"generation_status": generation_status},
    )
    service = DocumentService(AsyncMock())
    service.get_document_lifecycle_policy = AsyncMock(return_value=default_document_lifecycle_policy())

    blockers = await service.get_status_transition_blockers(document, "review")

    assert blockers == [
        f"Cannot transition {generation_status} document to 'review'. "
        "Document must be successfully regenerated with LLM before it can enter review/approval flow."
    ]


@pytest.mark.asyncio
async def test_update_document_blocks_failed_ai_document_from_formal_delivery():
    document = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        status="draft",
        approved_by=None,
        metadata_json={"generation_status": "failed"},
    )
    db = AsyncMock()
    service = DocumentService(db)
    service.get_document = AsyncMock(return_value=document)

    with pytest.raises(ValueError, match="Cannot transition failed document"):
        await service.update_document(
            document.id,
            document.tenant_id,
            status_update=DocumentStatusUpdate(status="review"),
        )
