"""Skill governance and interactive document generation engine tests."""

import json
import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-skill-governance-doc-generation.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-skill-governance-doc-generation-secret"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
import app.models.identity  # noqa: F401 - registers tenant/user tables for FK targets
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.agent.models import AgentSkill, AgentSkillBinding, SkillStatus, WorkflowDefinition
from app.domains.agent.schemas import SkillCatalogCreate, SkillCatalogUpdate
from app.domains.agent.service import AgentProfileService, SkillCatalogService
from app.domains.documents.models import Document, DocumentGenerationSection
from app.domains.documents.service import DocumentGenerationService


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


async def _confirm_all_generation_sections(
    service: DocumentGenerationService,
    *,
    session_id,
    tenant_id,
    user_id,
):
    while True:
        session = await service.get_generation_session(session_id, tenant_id)
        open_sections = [
            section
            for section in sorted(session.sections, key=lambda item: item.position)
            if section.status not in {"confirmed", "skipped"}
        ]
        if not open_sections:
            return
        current = next(
            (section for section in open_sections if section.section_key == session.current_section_key),
            open_sections[0],
        )
        await service.continue_generation_session(
            session_id=session_id,
            tenant_id=tenant_id,
            user_message=(
                f"{current.section_key} objective scope role process module exception security audit "
                "metrics acceptance traceability owner readiness confirmed evidence. "
            ) * 2,
            action="answer",
            created_by=user_id,
        )
        await service.continue_generation_session(
            session_id=session_id,
            tenant_id=tenant_id,
            user_message="ok",
            action="confirm",
            created_by=user_id,
        )


@pytest.mark.asyncio
async def test_seeded_skills_have_chinese_display_governance_and_lock_rules(db_session):
    tenant_id = uuid4()
    user_id = uuid4()

    service = SkillCatalogService(db_session)
    skills, total = await service.list_skills(
        tenant_id=tenant_id,
        created_by=user_id,
        status="published",
        limit=100,
    )

    by_name = {skill.name: skill for skill in skills}

    assert total >= 9
    assert by_name["DocumentReviewer"].display_name == "文档评审器"
    assert by_name["DocumentReviewer"].governance_scope == "system"
    assert by_name["DocumentReviewer"].is_locked == 1
    assert by_name["DocumentReviewer"].can_edit is False
    assert by_name["DocumentReviewer"].locked_reason == "系统级 Skill 由平台维护，当前租户不可修改。"

    assert by_name["BRDWritePipeline"].display_name == "BRD 写入管线"
    assert by_name["BRDWritePipeline"].governance_scope == "platform"
    assert by_name["BRDWritePipeline"].metadata_json["prototype_adaptation"] == "brd-write-pipeline"
    assert by_name["BRDWritePipeline"].metadata_json["test_scenario"]
    assert by_name["BRDWritePipeline"].metadata_json["sample_input"]["section_key"] == "brd.business_flows"
    assert "brd" in by_name["BRDWritePipeline"].supported_doc_types

    searched, searched_total = await service.list_skills(
        tenant_id=tenant_id,
        created_by=user_id,
        search="评审",
        limit=100,
    )
    assert searched_total >= 1
    assert any(skill.name == "DocumentReviewer" for skill in searched)

    with pytest.raises(ValueError, match="locked"):
        await service.update_skill(
            by_name["DocumentReviewer"].id,
            tenant_id,
            SkillCatalogUpdate(display_name="租户改名"),
        )

    with pytest.raises(ValueError, match="locked"):
        await service.set_skill_status(by_name["BRDWritePipeline"].id, tenant_id, "disabled")


@pytest.mark.asyncio
async def test_builtin_skill_samples_do_not_ship_placeholder_or_fixed_demo_markers(db_session):
    tenant_id = uuid4()
    user_id = uuid4()

    service = SkillCatalogService(db_session)
    skills, _ = await service.list_skills(
        tenant_id=tenant_id,
        created_by=user_id,
        status="published",
        limit=100,
    )

    forbidden_markers = (
        "[TODO]",
        "[PLACEHOLDER]",
        "demo-",
        "WMS",
        "仓储",
        "仓库",
        "出库",
        "发运",
        "扫码",
        "波次",
        "SKU",
        "warehouse_management",
        "logistics",
        "prd-shipping-review-001",
    )
    for skill in skills:
        sample_payload = {
            "sample_input": (skill.metadata_json or {}).get("sample_input"),
            "sample_context": (skill.metadata_json or {}).get("sample_context"),
            "test_scenario": (skill.metadata_json or {}).get("test_scenario"),
        }
        serialized = json.dumps(sample_payload, ensure_ascii=False)
        for marker in forbidden_markers:
            assert marker not in serialized, f"{skill.name} sample metadata contains {marker}"


@pytest.mark.asyncio
async def test_platform_skills_execute_with_concrete_sample_outputs(db_session):
    tenant_id = uuid4()
    user_id = uuid4()

    service = SkillCatalogService(db_session)
    skills, _ = await service.list_skills(
        tenant_id=tenant_id,
        created_by=user_id,
        status="published",
        limit=100,
    )
    by_name = {skill.name: skill for skill in skills}

    for skill_name in [
        "BRDDeepThinkingEngine",
        "BRDWritePipeline",
        "PRDTraceabilityMapper",
        "PRDSkeletonPlanner",
        "ChangeImpactAnalyzer",
        "TestCaseDesigner",
    ]:
        skill = by_name[skill_name]
        assert skill.metadata_json["sample_input"]
        assert skill.metadata_json["sample_context"]
        assert skill.metadata_json["test_scenario"]

        result = await service.test_skill(
            skill.id,
            tenant_id,
            skill.metadata_json["sample_input"],
            skill.metadata_json["sample_context"],
        )

        assert result is not None
        assert result["success"] is True
        assert result["mode"] == "builtin"
        assert result["output_data"]
        assert result["output_data"].get("summary")


@pytest.mark.asyncio
async def test_default_agent_profiles_are_seeded_with_project_skill_bindings(db_session):
    tenant_id = uuid4()
    user_id = uuid4()

    skill_service = SkillCatalogService(db_session)
    await skill_service.list_skills(
        tenant_id=tenant_id,
        created_by=user_id,
        status="published",
        limit=100,
    )

    agent_service = AgentProfileService(db_session)
    agents, total = await agent_service.list_agent_profiles(
        tenant_id=tenant_id,
        created_by=user_id,
        status="active",
        limit=100,
    )

    by_name = {agent.name: agent for agent in agents}

    assert total >= 4
    assert "BRD 业务分析顾问" in by_name
    assert "PRD 产品方案顾问" in by_name
    assert "文档质量评审顾问" in by_name
    assert "变更影响分析顾问" in by_name

    brd_agent = by_name["BRD 业务分析顾问"]
    assert brd_agent.agent_type == "brd"
    assert brd_agent.applicable_doc_types == ["brd"]
    assert brd_agent.human_review_required == 1
    assert brd_agent.workflow_definition_id is not None
    assert "knowledge_graph" in brd_agent.tool_names
    assert [binding.skill.name for binding in brd_agent.skill_bindings] == [
        "RequirementClarifier",
        "BRDDeepThinkingEngine",
        "BRDResearchAssistant",
        "BRDPatternLibrary",
        "BRDWritePipeline",
        "DocumentReviewer",
    ]

    workflow_names = {
        workflow.name
        for workflow in (
            await db_session.scalars(
                select(WorkflowDefinition).where(
                    WorkflowDefinition.tenant_id == tenant_id,
                    WorkflowDefinition.deleted_at.is_(None),
                )
            )
        ).all()
    }
    assert {
        "BRD Document Generation",
        "Document Quality Assessment",
        "Delivery Export Orchestration",
        "Change Impact Governance",
    }.issubset(workflow_names)
    assert all(agent.workflow_definition_id is not None for agent in agents)


@pytest.mark.asyncio
async def test_builtin_skill_seed_dedupes_historical_duplicate_rows(db_session):
    tenant_id = uuid4()
    user_id = uuid4()

    skill_service = SkillCatalogService(db_session)
    await skill_service.ensure_builtin_skills(tenant_id, user_id)
    result = await db_session.execute(
        select(AgentSkill).where(
            AgentSkill.tenant_id == tenant_id,
            AgentSkill.name == "BRDWritePipeline",
            AgentSkill.is_builtin == 1,
            AgentSkill.deleted_at.is_(None),
        )
    )
    original = result.scalar_one()

    duplicate = AgentSkill(
        tenant_id=tenant_id,
        name=original.name,
        display_name=original.display_name,
        description=original.description,
        skill_type=original.skill_type,
        category=original.category,
        input_schema_json=original.input_schema_json,
        output_schema_json=original.output_schema_json,
        supported_doc_types=original.supported_doc_types,
        supported_industries=original.supported_industries,
        version=original.version,
        status=SkillStatus.PUBLISHED.value,
        is_builtin=1,
        governance_scope=original.governance_scope,
        visibility=original.visibility,
        managed_by=original.managed_by,
        is_locked=original.is_locked,
        implementation_ref=original.implementation_ref,
        metadata_json=original.metadata_json,
        created_by=user_id,
    )
    db_session.add(duplicate)
    await db_session.flush()

    agent_service = AgentProfileService(db_session)
    agents, total = await agent_service.list_agent_profiles(
        tenant_id=tenant_id,
        created_by=user_id,
        status="active",
        limit=100,
    )

    active_result = await db_session.execute(
        select(AgentSkill).where(
            AgentSkill.tenant_id == tenant_id,
            AgentSkill.name == "BRDWritePipeline",
            AgentSkill.is_builtin == 1,
            AgentSkill.deleted_at.is_(None),
        )
    )
    active_skills = list(active_result.scalars().all())
    duplicate_bindings = await db_session.scalars(
        select(AgentSkillBinding).where(AgentSkillBinding.skill_id == duplicate.id)
    )

    assert total >= 4
    assert agents
    assert len(active_skills) == 1
    assert active_skills[0].id == original.id
    assert duplicate.deleted_at is not None
    assert list(duplicate_bindings.all()) == []


@pytest.mark.asyncio
async def test_custom_skill_can_be_edited_and_published_with_tenant_governance(db_session):
    tenant_id = uuid4()
    user_id = uuid4()

    service = SkillCatalogService(db_session)
    skill = await service.create_skill(
        tenant_id=tenant_id,
        created_by=user_id,
        data=SkillCatalogCreate(
            name="tenant.contract-review",
            display_name="合同条款评审",
            description="租户自定义合同条款评审 Skill",
            skill_type="quality",
            category="tenant",
            supported_doc_types=["brd"],
            status="draft",
        ),
    )

    assert skill.governance_scope == "tenant"
    assert skill.can_edit is True

    updated = await service.update_skill(
        skill.id,
        tenant_id,
        SkillCatalogUpdate(display_name="合同条款质量评审"),
    )
    assert updated.display_name == "合同条款质量评审"

    published = await service.set_skill_status(skill.id, tenant_id, "published")
    assert published.status == "published"


@pytest.mark.asyncio
async def test_interactive_brd_session_asks_drafts_advances_and_finalizes_document(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()

    service = DocumentGenerationService(db_session, llm_gateway=None)
    session = await service.start_generation_session(
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type="brd",
        title="WMS 升级 BRD",
        context={"project_name": "仓储管理升级", "language": "zh-CN"},
        created_by=user_id,
    )

    assert session.status == "active"
    assert session.current_section_key == "brd.background_goals"
    assert session.quality_summary_json["mode"] == "interactive"

    sections = await db_session.scalars(
        select(DocumentGenerationSection)
        .where(DocumentGenerationSection.session_id == session.id)
        .order_by(DocumentGenerationSection.position)
    )
    section_list = list(sections)
    assert [section.section_key for section in section_list] == [
        "brd.background_goals",
        "brd.stakeholders",
        "brd.business_flows",
        "brd.requirement_modules",
        "brd.non_functional",
    ]
    assert section_list[0].pending_questions_json[0].startswith("请先用一句话说明")

    response = await service.continue_generation_session(
        session_id=session.id,
        tenant_id=tenant_id,
        user_message="现有 WMS 波次分配依赖人工经验，错发率高，需要优化收货、上架、拣货、复核和发运。",
        action="answer",
        created_by=user_id,
    )

    assert response.session.current_section_key == "brd.background_goals"
    assert response.current_section.status == "drafted"
    assert "WMS 波次分配" in response.current_section.content
    assert response.assistant_message.startswith("已形成")
    assert response.current_section.quality_json["sufficiency_level"] in {"L2", "L3", "L4"}

    confirmed = await service.continue_generation_session(
        session_id=session.id,
        tenant_id=tenant_id,
        user_message="确认",
        action="confirm",
        created_by=user_id,
    )

    assert confirmed.current_section.section_key == "brd.stakeholders"
    assert confirmed.session.current_section_key == "brd.stakeholders"
    assert "背景与目标" in confirmed.section_summaries[0]["title"]
    assert confirmed.section_summaries[0]["status"] == "confirmed"

    with pytest.raises(ValueError, match="unresolved sections"):
        await service.finalize_generation_session(
            session_id=session.id,
            tenant_id=tenant_id,
            created_by=user_id,
        )

    await _confirm_all_generation_sections(
        service,
        session_id=session.id,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    document = await service.finalize_generation_session(
        session_id=session.id,
        tenant_id=tenant_id,
        created_by=user_id,
    )

    assert isinstance(document, Document)
    assert document.doc_type == "brd"
    assert document.status == "draft"
    assert "## 1. 背景与目标" in document.content
    assert "WMS 波次分配" in document.content
    assert "⚠️ 待确认" in document.content
    assert document.metadata_json["generation_session_id"] == str(session.id)
    assert document.metadata_json["generation_mode"] == "interactive"
