"""P3 structured template section and skill binding workflow tests."""

import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-template-sections-p3.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-template-sections-p3-secret"

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
import app.models.identity  # noqa: F401 - registers tenant/user tables for FK targets
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.agent.models import AgentSkill, SkillStatus
from app.domains.templates.models import Template, TemplateVersion
from app.domains.templates.schemas import TemplateSectionCreate
from app.domains.templates.service import TemplateSectionService


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


async def _template_version(db_session, tenant_id, user_id, doc_type="prd"):
    template = Template(
        tenant_id=tenant_id,
        name=f"{doc_type.upper()} standard template",
        description="Template section test fixture",
        doc_type=doc_type,
        version_count=1,
        is_active="true",
        created_by=user_id,
    )
    db_session.add(template)
    await db_session.flush()

    version = TemplateVersion(
        tenant_id=tenant_id,
        template_id=template.id,
        version=1,
        content=b"# {{project_name}}",
        file_hash="sha256-template-sections",
        placeholder_schema=[],
        page_types=[],
        is_active="true",
        created_by=user_id,
    )
    db_session.add(version)
    await db_session.flush()
    return template, version


@pytest.mark.asyncio
async def test_seed_standard_sections_creates_ordered_structured_prd_sections(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    template, version = await _template_version(db_session, tenant_id, user_id, doc_type="prd")

    service = TemplateSectionService(db_session)
    sections = await service.seed_standard_sections(
        tenant_id=tenant_id,
        template_version_id=version.id,
        doc_type="prd",
        created_by=user_id,
    )

    assert [section.section_key for section in sections] == [
        "prd.overview",
        "prd.goals",
        "prd.scope",
        "prd.requirements",
        "prd.metrics",
    ]
    assert sections[0].title == "产品概述"
    assert sections[0].position == 0
    assert sections[3].title == "功能需求"
    assert sections[3].required_inputs == ["user_personas", "user_journeys", "business_rules"]
    assert sections[3].quality_rules[0]["rule"] == "每条需求必须包含验收标准"
    assert "PRD" in sections[3].prompt

    listed = await service.list_template_sections(
        tenant_id=tenant_id,
        template_id=template.id,
    )

    assert [section.id for section in listed] == [section.id for section in sections]


@pytest.mark.asyncio
async def test_section_skill_bindings_replace_order_and_reject_cross_tenant_skills(db_session):
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    user_id = uuid4()
    _template, version = await _template_version(db_session, tenant_id, user_id, doc_type="urs")

    reviewer = AgentSkill(
        tenant_id=tenant_id,
        name="DocumentReviewer",
        description="Review section quality",
        skill_type="quality",
        category="review",
        input_schema_json={},
        output_schema_json={},
        supported_doc_types=["urs"],
        supported_industries=[],
        version="1.0.0",
        status=SkillStatus.PUBLISHED.value,
        is_builtin=1,
        implementation_ref="builtin:DocumentReviewer",
        metadata_json={},
        created_by=user_id,
    )
    clarifier = AgentSkill(
        tenant_id=tenant_id,
        name="RequirementClarifier",
        description="Clarify ambiguous requirements",
        skill_type="clarification",
        category="requirements",
        input_schema_json={},
        output_schema_json={},
        supported_doc_types=["urs"],
        supported_industries=[],
        version="1.0.0",
        status=SkillStatus.PUBLISHED.value,
        is_builtin=1,
        implementation_ref="builtin:RequirementClarifier",
        metadata_json={},
        created_by=user_id,
    )
    foreign_skill = AgentSkill(
        tenant_id=other_tenant_id,
        name="ForeignSkill",
        description="Must not be bindable",
        skill_type="quality",
        category="review",
        input_schema_json={},
        output_schema_json={},
        supported_doc_types=["urs"],
        supported_industries=[],
        version="1.0.0",
        status=SkillStatus.PUBLISHED.value,
        is_builtin=0,
        implementation_ref=None,
        metadata_json={},
        created_by=user_id,
    )
    db_session.add_all([reviewer, clarifier, foreign_skill])
    await db_session.flush()

    service = TemplateSectionService(db_session)
    section = await service.create_template_section(
        tenant_id=tenant_id,
        template_version_id=version.id,
        data=TemplateSectionCreate(
            section_key="urs.business-context",
            title="业务背景",
            level=1,
            position=0,
            content_requirement="说明业务背景、目标用户和当前痛点。",
            prompt="请按咨询交付标准补充业务背景。",
            required_inputs=["project_background"],
            quality_rules=[{"rule": "必须说明业务目标", "severity": "high"}],
        ),
        created_by=user_id,
    )

    bindings = await service.replace_section_skill_bindings(
        tenant_id=tenant_id,
        section_id=section.id,
        skill_ids=[clarifier.id, reviewer.id],
        created_by=user_id,
    )

    assert [binding.skill_id for binding in bindings] == [clarifier.id, reviewer.id]
    assert [binding.order_index for binding in bindings] == [0, 1]

    replacement = await service.replace_section_skill_bindings(
        tenant_id=tenant_id,
        section_id=section.id,
        skill_ids=[reviewer.id],
        created_by=user_id,
    )

    assert [binding.skill_id for binding in replacement] == [reviewer.id]
    assert replacement[0].order_index == 0

    with pytest.raises(ValueError, match="Skill does not belong to tenant"):
        await service.replace_section_skill_bindings(
            tenant_id=tenant_id,
            section_id=section.id,
            skill_ids=[foreign_skill.id],
            created_by=user_id,
        )
