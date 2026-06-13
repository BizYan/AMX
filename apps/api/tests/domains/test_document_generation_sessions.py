"""API tests for interactive document generation sessions."""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-document-generation-sessions.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-document-generation-sessions-secret"

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
import app.models.identity  # noqa: F401 - registers tenant/user tables for FK targets
import app.models.projects  # noqa: F401 - registers project tables for FK targets
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.documents import router as documents_router
from app.domains.documents.models import (
    DocumentGenerationSection,
    DocumentGenerationSession,
    DocumentGenerationStep,
    GenerationSectionStatus,
    GenerationSessionStatus,
)
from app.models.projects import Project


@pytest.fixture
async def db_session():
    """Create a disposable async SQLite database for document session API tests."""
    deduplicate_indexes()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def api_client(db_session):
    """Expose the documents router with a fixed authenticated user."""
    tenant_id = uuid4()
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id)

    async def override_db():
        yield db_session

    async def override_current_user():
        return user

    app = FastAPI()
    app.include_router(documents_router.router, prefix="/api/v1/documents")
    app.dependency_overrides[documents_router.get_db] = override_db
    app.dependency_overrides[documents_router.get_current_user] = override_current_user
    app.dependency_overrides[documents_router.get_llm_gateway] = lambda: None

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client, tenant_id, user_id


def _project(*, project_id, tenant_id, slug: str) -> Project:
    return Project(
        id=project_id,
        tenant_id=tenant_id,
        name=slug,
        slug=slug,
        status="active",
    )


async def _session(
    db_session,
    *,
    tenant_id,
    project_id,
    created_by,
    doc_type: str,
    title: str,
    status: str = GenerationSessionStatus.ACTIVE.value,
    updated_at: datetime | None = None,
) -> DocumentGenerationSession:
    now = updated_at or datetime.now(timezone.utc)
    session = DocumentGenerationSession(
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type=doc_type,
        title=title,
        status=status,
        generation_mode="interactive",
        current_section_key=f"{doc_type}.overview",
        context_json={"language": "zh-CN"},
        stash_json={"cross_section_facts": []},
        quality_summary_json={"mode": "interactive", "section_count": 1},
        created_by=created_by,
        created_at=now,
        updated_at=now,
        finalized_at=now if status == GenerationSessionStatus.FINALIZED.value else None,
    )
    db_session.add(session)
    await db_session.flush()
    section = DocumentGenerationSection(
        tenant_id=tenant_id,
        session_id=session.id,
        section_key=f"{doc_type}.overview",
        title="背景与目标",
        position=0,
        status=GenerationSectionStatus.PENDING.value,
        prompt="逐步补充章节内容。",
        content_requirement="说明背景、目标和约束。",
        pending_questions_json=["请说明业务背景。"],
        confirmed_facts_json=[],
        quality_json={"score": 0},
        required_inputs=[],
        quality_rules=[],
    )
    step = DocumentGenerationStep(
        tenant_id=tenant_id,
        session_id=session.id,
        step_index=0,
        role="assistant",
        action_type="ask",
        section_key=section.section_key,
        message="请说明业务背景。",
        patch_json={},
        quality_json={},
        created_by=created_by,
    )
    db_session.add_all([section, step])
    await db_session.flush()
    return session


@pytest.mark.asyncio
async def test_list_generation_sessions_filters_project_status_and_sorts_desc(db_session, api_client):
    client, tenant_id, user_id = api_client
    project_id = uuid4()
    other_project_id = uuid4()
    other_tenant_id = uuid4()
    now = datetime.now(timezone.utc)
    db_session.add_all([
        _project(project_id=project_id, tenant_id=tenant_id, slug="target"),
        _project(project_id=other_project_id, tenant_id=tenant_id, slug="other-project"),
        _project(project_id=uuid4(), tenant_id=other_tenant_id, slug="other-tenant"),
    ])
    await db_session.flush()

    older = await _session(
        db_session,
        tenant_id=tenant_id,
        project_id=project_id,
        created_by=user_id,
        doc_type="brd",
        title="较早 BRD 会话",
        updated_at=now - timedelta(hours=2),
    )
    newer = await _session(
        db_session,
        tenant_id=tenant_id,
        project_id=project_id,
        created_by=user_id,
        doc_type="prd",
        title="最新 PRD 会话",
        status=GenerationSessionStatus.FINALIZED.value,
        updated_at=now - timedelta(minutes=10),
    )
    await _session(
        db_session,
        tenant_id=tenant_id,
        project_id=other_project_id,
        created_by=user_id,
        doc_type="brd",
        title="其它项目会话",
        updated_at=now,
    )
    await _session(
        db_session,
        tenant_id=other_tenant_id,
        project_id=uuid4(),
        created_by=user_id,
        doc_type="brd",
        title="其它租户会话",
        updated_at=now,
    )

    response = await client.get(f"/api/v1/documents/generation-sessions?project_id={project_id}")

    assert response.status_code == 200
    sessions = response.json()
    assert [item["id"] for item in sessions] == [str(newer.id), str(older.id)]
    assert sessions[0]["sections"][0]["title"] == "背景与目标"
    assert sessions[0]["steps"][0]["action_type"] == "ask"

    active_response = await client.get(
        f"/api/v1/documents/generation-sessions?project_id={project_id}&status=active"
    )

    assert active_response.status_code == 200
    assert [item["id"] for item in active_response.json()] == [str(older.id)]


@pytest.mark.asyncio
async def test_cancel_generation_session_marks_cancelled_and_appends_audit_step(db_session, api_client):
    client, tenant_id, user_id = api_client
    project_id = uuid4()
    db_session.add(_project(project_id=project_id, tenant_id=tenant_id, slug="cancel-target"))
    await db_session.flush()
    session = await _session(
        db_session,
        tenant_id=tenant_id,
        project_id=project_id,
        created_by=user_id,
        doc_type="brd",
        title="待取消会话",
    )

    response = await client.post(f"/api/v1/documents/generation-sessions/{session.id}/cancel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "cancelled"
    assert payload["steps"][-1]["action_type"] == "cancel"
    assert payload["steps"][-1]["message"] == "用户取消了文档生成会话。"

    refreshed = await db_session.get(DocumentGenerationSession, session.id)
    assert refreshed is not None
    assert refreshed.status == GenerationSessionStatus.CANCELLED.value
    steps = await db_session.scalars(
        select(DocumentGenerationStep)
        .where(DocumentGenerationStep.session_id == session.id)
        .order_by(DocumentGenerationStep.step_index)
    )
    assert [step.action_type for step in steps][-1] == "cancel"


@pytest.mark.asyncio
async def test_cancel_generation_session_rejects_finalized_session(db_session, api_client):
    client, tenant_id, user_id = api_client
    project_id = uuid4()
    db_session.add(_project(project_id=project_id, tenant_id=tenant_id, slug="finalized-target"))
    await db_session.flush()
    session = await _session(
        db_session,
        tenant_id=tenant_id,
        project_id=project_id,
        created_by=user_id,
        doc_type="prd",
        title="已完成会话",
        status=GenerationSessionStatus.FINALIZED.value,
    )

    response = await client.post(f"/api/v1/documents/generation-sessions/{session.id}/cancel")

    assert response.status_code == 400
    assert "finalized" in response.json()["detail"]
    refreshed = await db_session.get(DocumentGenerationSession, session.id)
    assert refreshed is not None
    assert refreshed.status == GenerationSessionStatus.FINALIZED.value
