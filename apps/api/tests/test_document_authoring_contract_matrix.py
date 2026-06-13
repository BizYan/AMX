"""Contract tests for full conversational document authoring sessions."""

import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-document-authoring-contract-matrix.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-document-authoring-contract-matrix-secret"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
import app.domains.agent.models  # noqa: F401 - registers skill tables
import app.domains.change.models  # noqa: F401 - registers change tables
import app.domains.collaboration.models  # noqa: F401 - registers collaboration tables
import app.domains.export.models  # noqa: F401 - registers export tables
import app.domains.knowledge.models  # noqa: F401 - registers knowledge tables
import app.domains.templates.models  # noqa: F401 - registers template tables
import app.models.identity  # noqa: F401 - registers tenant/user tables for FK targets
import app.models.projects  # noqa: F401 - registers project tables for FK targets
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.documents.models import DocumentGenerationSection, DocumentType
from app.domains.documents.service import DocumentGenerationService


CORE_DOCUMENT_TYPES = [
    DocumentType.URS.value,
    DocumentType.BRD.value,
    DocumentType.PRD.value,
    DocumentType.USER_STORY.value,
    DocumentType.DETAILED_DESIGN.value,
    DocumentType.INTERFACE.value,
    DocumentType.DATA_DICTIONARY.value,
    DocumentType.TEST_CASE.value,
]


@pytest.fixture
async def db_session():
    """Create a disposable async SQLite database with registered domain models."""
    deduplicate_indexes()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


async def _session_sections(db_session, session_id):
    result = await db_session.execute(
        select(DocumentGenerationSection)
        .where(DocumentGenerationSection.session_id == session_id)
        .order_by(DocumentGenerationSection.position)
    )
    return list(result.scalars().all())


async def _complete_interactive_session(service, db_session, *, tenant_id, user_id, project_id, doc_type):
    session = await service.start_generation_session(
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type=doc_type,
        title=f"{doc_type.upper()} authoring contract",
        context={
            "project_name": "WMS 升级",
            "language": "zh-CN",
            "requirements": "覆盖角色、流程、异常、指标、验收和交付边界。",
        },
        created_by=user_id,
    )
    section_count = len(await _session_sections(db_session, session.id))

    last_turn = None
    for index in range(section_count):
        section_key = session.current_section_key
        last_turn = await service.continue_generation_session(
            session_id=session.id,
            tenant_id=tenant_id,
            user_message=(
                f"第 {index + 1} 节补充：明确业务目标、关键角色、流程节点、"
                "异常处理、质量指标、验收条件和责任边界。"
            ),
            action="answer",
            created_by=user_id,
        )
        assert last_turn.current_section.section_key == section_key
        assert last_turn.current_section.status == "drafted"
        assert last_turn.write_log[-1]["verified"] is True
        assert last_turn.pending_confirmations

        last_turn = await service.continue_generation_session(
            session_id=session.id,
            tenant_id=tenant_id,
            user_message="确认",
            action="confirm",
            created_by=user_id,
        )
        session = last_turn.session
        assert not [
            item
            for item in last_turn.pending_confirmations
            if item.get("section_key") == section_key
        ]

    return session, last_turn


@pytest.mark.asyncio
@pytest.mark.parametrize("doc_type", CORE_DOCUMENT_TYPES)
async def test_core_document_type_authoring_contract_reaches_delivery_ready_metadata(db_session, doc_type):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    service = DocumentGenerationService(db_session, llm_gateway=None)

    session, last_turn = await _complete_interactive_session(
        service,
        db_session,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        doc_type=doc_type,
    )

    sections = await _session_sections(db_session, session.id)
    assert sections
    assert all(section.status == "confirmed" for section in sections)

    quality_gate = last_turn.quality_gate
    assert quality_gate["ready"] is True
    assert quality_gate["export_ready"] is True
    assert quality_gate["review_ready"] is True
    assert quality_gate["blockers"] == []

    document = await service.finalize_generation_session(
        session_id=session.id,
        tenant_id=tenant_id,
        created_by=user_id,
    )

    delivery = document.metadata_json["delivery"]
    assert document.doc_type == doc_type
    assert delivery["completion_ratio"] == 1
    assert delivery["pending_confirmations"] == []
    assert delivery["write_log_count"] >= len(sections) * 2
    assert delivery["quality_summary"]["delivery_readiness"]["ready"] is True
    assert len(document.metadata_json["section_summaries"]) == len(sections)
    assert all(item["status"] == "confirmed" for item in document.metadata_json["section_summaries"])
    assert "待确认" in document.content
