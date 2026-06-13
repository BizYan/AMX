"""Full project document delivery workbench tests."""

import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-full-document-delivery-workbench.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-full-document-delivery-workbench-secret"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import app.domains.agent.models  # noqa: F401 - registers skill tables for template bindings
import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
import app.domains.change.models  # noqa: F401 - registers change tables
import app.domains.collaboration.models  # noqa: F401 - registers collaboration tables
import app.domains.export.models  # noqa: F401 - registers export tables
import app.domains.identity.models  # noqa: F401 - registers policy and audit tables
import app.domains.knowledge.models  # noqa: F401 - registers knowledge tables
import app.domains.ops.models  # noqa: F401 - registers observability and quota tables
import app.domains.providers.models  # noqa: F401 - registers provider tables
import app.domains.templates.models  # noqa: F401 - registers template tables
import app.models.identity  # noqa: F401 - registers tenant/user tables for FK targets
import app.models.projects  # noqa: F401 - registers project tables for FK targets
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.agent.models import AgentProfile, AgentSkill, WorkflowDefinition
from app.domains.collaboration.models import DocumentComment
from app.domains.documents.models import Document, DocumentGenerationSection, DocumentType
from app.domains.documents.service import DocumentGenerationService
from app.domains.export.models import ExportJob
from app.domains.identity.models import AuditLog
from app.domains.providers.models import Provider, ProviderStatus, ProviderType
from app.domains.projects.service import ProjectService
from app.domains.templates.models import Template, TemplateSection, TemplateSectionSkillBinding, TemplateVersion
from app.models.identity import Role, User
from app.models.projects import Project


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


async def _resolve_generation_session(
    service: DocumentGenerationService,
    *,
    session_id,
    tenant_id,
    user_id,
    skip_section_keys: set[str] | None = None,
):
    """Resolve a session through the public conversational service methods."""
    skip_section_keys = skip_section_keys or set()
    while True:
        session = await service.get_generation_session(session_id, tenant_id)
        open_sections = [
            section
            for section in sorted(session.sections, key=lambda item: item.position)
            if section.status not in {"confirmed", "skipped"}
        ]
        if not open_sections:
            return await service.get_generation_session(session_id, tenant_id)

        current = next(
            (section for section in open_sections if section.section_key == session.current_section_key),
            open_sections[0],
        )
        if current.section_key in skip_section_keys:
            await service.continue_generation_session(
                session_id=session_id,
                tenant_id=tenant_id,
                user_message=f"skip optional section {current.section_key}",
                action="skip",
                created_by=user_id,
            )
            continue

        fact = (
            f"{current.section_key} objective scope role process module exception security audit "
            "metrics acceptance traceability owner release readiness data interface test coverage "
            "confirmed evidence. "
        ) * 2
        await service.continue_generation_session(
            session_id=session_id,
            tenant_id=tenant_id,
            user_message=fact,
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
async def test_all_core_document_types_start_structured_interactive_sessions(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    service = DocumentGenerationService(db_session, llm_gateway=None)

    for doc_type in CORE_DOCUMENT_TYPES:
        session = await service.start_generation_session(
            tenant_id=tenant_id,
            project_id=project_id,
            doc_type=doc_type,
            title=f"{doc_type} workbench session",
            context={"language": "zh-CN"},
            created_by=user_id,
        )

        sections = list(
            (
                await db_session.execute(
                    select(DocumentGenerationSection)
                    .where(DocumentGenerationSection.session_id == session.id)
                    .order_by(DocumentGenerationSection.position)
                )
            )
            .scalars()
            .all()
        )
        assert len(sections) >= 3
        assert session.current_section_key == sections[0].section_key
        assert session.context_json["entity_state"]["doc_type"] == doc_type
        assert session.context_json["entity_state"]["slots"]
        assert session.stash_json["write_log"] == []
        assert session.quality_summary_json["source"] == "full_delivery_workbench"
        for section in sections:
            assert section.required_inputs
            assert section.quality_rules
            assert section.pending_questions_json[0]


@pytest.mark.asyncio
async def test_conversational_write_verify_revise_and_finalize_metadata(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    service = DocumentGenerationService(db_session, llm_gateway=None)
    session = await service.start_generation_session(
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type=DocumentType.TEST_CASE.value,
        title="出库复核测试用例",
        context={"language": "zh-CN"},
        created_by=user_id,
    )

    answered = await service.continue_generation_session(
        session_id=session.id,
        tenant_id=tenant_id,
        user_message=(
            "测试范围覆盖出库复核、异常拦截和发运确认，优先级为高。"
            " 需要覆盖目标、角色、流程、异常、模块、安全、审计、指标、验收、发运、人工优化和自动化回归。"
        ),
        action="answer",
        created_by=user_id,
    )

    assert answered.current_section.status == "drafted"
    assert answered.write_log[-1]["verified"] is True
    assert "测试设计" in answered.write_log[-1]["skill_labels"]
    assert answered.skill_trace
    assert answered.pending_confirmations[0]["section_key"] == "test_case.scope_strategy"
    assert answered.quality_gate["ready"] is False

    revised = await service.continue_generation_session(
        session_id=session.id,
        tenant_id=tenant_id,
        user_message="测试范围=>测试覆盖范围",
        action="revise",
        created_by=user_id,
    )

    assert revised.write_log[-1]["patch_type"] == "replace"
    assert revised.write_log[-1]["verified"] is True
    assert "测试覆盖范围" in revised.current_section.content

    confirmed = await service.continue_generation_session(
        session_id=session.id,
        tenant_id=tenant_id,
        user_message="确认",
        action="confirm",
        created_by=user_id,
    )

    assert confirmed.section_summaries[0]["status"] == "confirmed"
    assert confirmed.current_section.section_key == "test_case.steps_data"
    assert confirmed.pending_confirmations == []

    with pytest.raises(ValueError, match="unresolved sections"):
        await service.finalize_generation_session(
            session_id=session.id,
            tenant_id=tenant_id,
            created_by=user_id,
        )

    await _resolve_generation_session(
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

    assert document.doc_type == DocumentType.TEST_CASE.value
    assert document.metadata_json["delivery"]["write_log_count"] >= 3
    assert document.metadata_json["delivery"]["upstream_dependencies"] == [
        "prd",
        "detailed_design",
        "interface",
        "user_story",
    ]
    assert document.metadata_json["delivery"]["delivery_readiness"]["ready"] is True
    assert document.metadata_json["delivery"]["quality_summary"]["delivery_readiness"]["ready"] is True
    assert "测试覆盖范围" in document.content


@pytest.mark.asyncio
async def test_finalize_blocks_unresolved_pending_low_quality_and_required_skips(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    service = DocumentGenerationService(db_session, llm_gateway=None)

    session = await service.start_generation_session(
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type=DocumentType.PRD.value,
        title="PRD blocked gates",
        context={"language": "zh-CN"},
        created_by=user_id,
    )

    with pytest.raises(ValueError, match="unresolved sections"):
        await service.finalize_generation_session(session.id, tenant_id, user_id)

    await service.continue_generation_session(
        session_id=session.id,
        tenant_id=tenant_id,
        user_message="short",
        action="answer",
        created_by=user_id,
    )
    with pytest.raises(ValueError, match="pending confirmations"):
        await service.finalize_generation_session(session.id, tenant_id, user_id)

    await service.continue_generation_session(
        session_id=session.id,
        tenant_id=tenant_id,
        user_message="ok",
        action="confirm",
        created_by=user_id,
    )
    await _resolve_generation_session(
        service,
        session_id=session.id,
        tenant_id=tenant_id,
        user_id=user_id,
        skip_section_keys={"prd.metrics_release"},
    )
    with pytest.raises(ValueError, match="low quality sections"):
        await service.finalize_generation_session(session.id, tenant_id, user_id)

    required_skip_session = await service.start_generation_session(
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type=DocumentType.BRD.value,
        title="BRD required skip",
        context={"language": "zh-CN"},
        created_by=user_id,
    )
    await service.continue_generation_session(
        session_id=required_skip_session.id,
        tenant_id=tenant_id,
        user_message="skip required first section",
        action="skip",
        created_by=user_id,
    )
    await _resolve_generation_session(
        service,
        session_id=required_skip_session.id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    with pytest.raises(ValueError, match="required sections skipped"):
        await service.finalize_generation_session(required_skip_session.id, tenant_id, user_id)


@pytest.mark.asyncio
async def test_finalize_succeeds_across_doc_types_and_optional_skips(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    service = DocumentGenerationService(db_session, llm_gateway=None)

    cases = [
        (DocumentType.URS.value, set()),
        (DocumentType.PRD.value, {"prd.metrics_release"}),
        (DocumentType.DATA_DICTIONARY.value, {"data_dictionary.retention"}),
    ]
    for doc_type, skip_keys in cases:
        session = await service.start_generation_session(
            tenant_id=tenant_id,
            project_id=project_id,
            doc_type=doc_type,
            title=f"{doc_type} finalization gates",
            context={"language": "zh-CN"},
            created_by=user_id,
        )
        await _resolve_generation_session(
            service,
            session_id=session.id,
            tenant_id=tenant_id,
            user_id=user_id,
            skip_section_keys=skip_keys,
        )

        document = await service.finalize_generation_session(session.id, tenant_id, user_id)

        readiness = document.metadata_json["delivery"]["delivery_readiness"]
        assert document.doc_type == doc_type
        assert readiness["doc_type"] == doc_type
        assert readiness["ready"] is True
        assert readiness["required_sections_confirmed"] is True
        assert readiness["resolved_sections"] == readiness["section_count"]
        assert not readiness["blockers"]
        for skipped_key in skip_keys:
            assert skipped_key in readiness["skipped_sections"]


@pytest.mark.asyncio
async def test_project_document_workbench_returns_chain_sessions_and_readiness(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    db_session.add(
        Project(
            id=project_id,
            tenant_id=tenant_id,
            name="全链路交付项目",
            slug="full-delivery",
            status="active",
            owner_id=user_id,
        )
    )
    db_session.add(
        urs_document := Document(
            tenant_id=tenant_id,
            project_id=project_id,
            doc_type=DocumentType.URS.value,
            title="用户需求规格说明书",
            content="# URS",
            status="published",
            version=1,
            created_by=user_id,
            metadata_json={
                "delivery": {
                    "completion_ratio": 1,
                    "quality_summary": {"level": "L4"},
                    "upstream_dependencies": [],
                    "pending_confirmations": [],
                }
            },
        )
    )
    db_session.add(
        brd_document := Document(
            tenant_id=tenant_id,
            project_id=project_id,
            doc_type=DocumentType.BRD.value,
            title="业务需求文档",
            content="# BRD",
            status="published",
            version=1,
            created_by=user_id,
            metadata_json={
                "delivery": {
                    "completion_ratio": 1,
                    "quality_summary": {"level": "L4"},
                    "upstream_dependencies": ["urs"],
                    "pending_confirmations": [],
                }
            },
        )
    )
    template = Template(
        tenant_id=tenant_id,
        name="BRD 标准模板",
        description="用于项目文档工作台覆盖率测试",
        doc_type=DocumentType.BRD.value,
        version_count=1,
        is_active="true",
        created_by=user_id,
    )
    db_session.add(template)
    await db_session.flush()
    template_version = TemplateVersion(
        tenant_id=tenant_id,
        template_id=template.id,
        version=1,
        is_active="true",
        created_by=user_id,
    )
    db_session.add(template_version)
    await db_session.flush()
    section = TemplateSection(
        tenant_id=tenant_id,
        template_version_id=template_version.id,
        section_key="brd.background_goals",
        title="背景与目标",
        level=1,
        position=1,
        content_requirement="说明背景与目标",
        prompt="澄清业务背景",
        required_inputs=["pain_points"],
        quality_rules=[{"rule": "目标可追溯"}],
        created_by=user_id,
    )
    db_session.add(section)
    await db_session.flush()
    db_session.add(
        TemplateSectionSkillBinding(
            tenant_id=tenant_id,
            section_id=section.id,
            skill_id=uuid4(),
            order_index=0,
            is_required=1,
            created_by=user_id,
        )
    )
    db_session.add(
        DocumentComment(
            tenant_id=tenant_id,
            document_id=urs_document.id,
            user_id=user_id,
            content="需要确认验收指标",
            resolved=False,
        )
    )
    db_session.add(
        ExportJob(
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=urs_document.id,
            export_type="project_package",
            status="completed",
            created_by=user_id,
        )
    )
    generation = DocumentGenerationService(db_session, llm_gateway=None)
    session = await generation.start_generation_session(
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type=DocumentType.PRD.value,
        title="产品需求文档会话",
        context={"language": "zh-CN"},
        created_by=user_id,
    )
    await db_session.flush()

    workbench = await ProjectService(db_session).get_document_workbench(project_id, tenant_id)

    assert workbench is not None
    assert len(workbench["delivery_chain"]) == 8
    assert workbench["delivery_chain"][0]["doc_type"] == "urs"
    assert workbench["delivery_chain"][0]["completion_ratio"] == 1
    assert workbench["delivery_chain"][1]["upstream_dependencies"] == ["urs"]
    assert workbench["active_sessions"][0]["id"] == session.id
    assert workbench["active_sessions"][0]["doc_type"] == "prd"
    assert workbench["readiness"]["export_ready"] is False
    assert any(risk["code"] == "missing_delivery_documents" for risk in workbench["risks"])
    assert workbench["workflow_lanes"]
    assert workbench["quality_gates"]
    assert workbench["template_coverage"][1]["doc_type"] == "brd"
    assert workbench["template_coverage"][1]["template_available"] is True
    assert workbench["template_coverage"][1]["section_count"] == 1
    assert workbench["template_coverage"][1]["skill_binding_count"] == 1
    assert workbench["export_package"]["latest_job_status"] == "completed"
    assert workbench["export_package"]["ready"] is False
    assert workbench["collaboration_summary"]["unresolved_comment_count"] == 1
    assert len(workbench["package_manifest"]) == 8
    assert workbench["package_manifest"][0]["doc_type"] == "urs"
    assert workbench["package_manifest"][0]["included"] is True
    assert workbench["package_manifest"][0]["release_ready"] is True
    assert workbench["package_manifest"][1]["document_id"] == brd_document.id
    assert any(
        action["code"] == "missing_reference_urs_brd"
        for action in workbench["traceability_actions"]
    )
    assert any(
        action["code"] == "resume_authoring_sessions"
        for action in workbench["collaboration_actions"]
    )
    assert any(
        action["code"] == "resolve_document_comments"
        for action in workbench["collaboration_actions"]
    )
    assert workbench["source_coverage"]["status"] == "blocked"
    assert workbench["source_coverage"]["blockers"] == ["尚未上传项目资料"]
    assert len(workbench["control_matrix"]) == 8
    assert workbench["control_matrix"][0]["doc_type"] == "urs"
    assert workbench["control_matrix"][0]["traceability_gap_count"] == 1
    assert workbench["control_matrix"][1]["doc_type"] == "brd"
    assert workbench["control_matrix"][1]["document_id"] == brd_document.id
    assert workbench["control_matrix"][2]["doc_type"] == "prd"
    assert workbench["control_matrix"][2]["stage"] == "authoring"
    assert workbench["control_matrix"][2]["primary_action"]["code"] == "resume_authoring"


@pytest.mark.asyncio
async def test_system_delivery_overview_includes_completion_matrix_and_gap_queue(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    db_session.add(
        User(
            id=user_id,
            tenant_id=tenant_id,
            email="lead@example.test",
            hashed_password="hashed",
            full_name="Delivery Lead",
            is_active=True,
        )
    )
    db_session.add(
        Role(
            tenant_id=tenant_id,
            name="Project Lead",
            description="Owns delivery readiness",
            permissions={"projects": ["read", "write"]},
        )
    )
    db_session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action="team.role_assigned",
            resource_type="role",
        )
    )
    db_session.add(
        Project(
            id=project_id,
            tenant_id=tenant_id,
            name="Completion Matrix Project",
            slug="completion-matrix",
            status="active",
            owner_id=user_id,
        )
    )
    db_session.add(
        Document(
            tenant_id=tenant_id,
            project_id=project_id,
            doc_type=DocumentType.URS.value,
            title="URS",
            content="# URS",
            status="published",
            version=1,
            created_by=user_id,
            metadata_json={
                "delivery": {
                    "completion_ratio": 1,
                    "quality_summary": {"level": "L4"},
                    "upstream_dependencies": [],
                    "pending_confirmations": [],
                }
            },
        )
    )
    db_session.add(
        AgentSkill(
            tenant_id=tenant_id,
            name="requirement_clarifier",
            display_name="需求澄清",
            description="Clarifies requirements before writing.",
            skill_type="document",
            category="requirements",
            status="published",
            is_builtin=1,
            governance_scope="platform",
            visibility="tenant",
            managed_by="platform",
            is_locked=1,
            created_by=user_id,
        )
    )
    db_session.add(
        AgentProfile(
            tenant_id=tenant_id,
            name="需求顾问",
            description="Runs document authoring support.",
            agent_type="document",
            applicable_doc_types=["urs", "brd", "prd"],
            status="active",
            created_by=user_id,
        )
    )
    db_session.add(
        WorkflowDefinition(
            tenant_id=tenant_id,
            name="Document Authoring Flow",
            description="Author and review documents.",
            category="document_generation",
            version_count=1,
            is_active=1,
            created_by=user_id,
        )
    )
    db_session.add(
        Provider(
            tenant_id=tenant_id,
            name="Live LLM",
            provider_type=ProviderType.LLM.value,
            status=ProviderStatus.ACTIVE.value,
            config_json={"api_key": "live-secret"},
        )
    )
    template = Template(
        tenant_id=tenant_id,
        name="URS Template",
        description="Template for URS.",
        doc_type=DocumentType.URS.value,
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
        is_active="true",
        created_by=user_id,
    )
    db_session.add(version)
    await db_session.flush()
    db_session.add(
        TemplateSection(
            tenant_id=tenant_id,
            template_version_id=version.id,
            section_key="urs.scope",
            title="Scope",
            level=1,
            position=1,
            content_requirement="Describe scope.",
            prompt="Clarify scope.",
            required_inputs=["scope"],
            quality_rules=[{"rule": "traceable"}],
            created_by=user_id,
        )
    )
    db_session.add(
        ExportJob(
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=None,
            export_type="project_package",
            status="completed",
            created_by=user_id,
        )
    )
    await db_session.flush()

    overview = await ProjectService(db_session).get_system_delivery_overview(
        tenant_id=tenant_id,
        user_id=user_id,
        limit=10,
    )

    capabilities = {item["key"]: item for item in overview["completion_capabilities"]}
    gaps = {item["capability_key"] for item in overview["completion_gaps"]}

    assert overview["completion_score"] > 0
    assert capabilities["intelligent_orchestration"]["score"] > 0
    assert capabilities["provider_operations"]["status"] == "ready"
    assert capabilities["team_permissions"]["status"] == "ready"
    assert capabilities["source_knowledge"]["status"] == "blocked"
    assert "source_knowledge" in gaps
