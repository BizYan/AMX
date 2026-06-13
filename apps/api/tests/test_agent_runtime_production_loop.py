"""Production runtime loop coverage for agent orchestration."""

import asyncio
import os
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-agent-runtime-prod-loop.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-agent-runtime-prod-loop-secret"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
import app.models.identity  # noqa: F401 - registers tenant/user tables for FK targets
import app.domains.projects.models  # noqa: F401 - registers project extension relationships before mapper configuration
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.agent.models import (
    AgentEvent,
    AgentProfile,
    AgentRun,
    AgentSkill,
    WorkflowDefinition,
    WorkflowVersion,
)
from app.domains.agent.schemas import AgentProfileCreate, AgentRunResponse
from app.domains.agent.service import (
    AgentProfileService,
    AgentRunService,
    DAGExecutor,
    SkillCatalogService,
    SkillService,
    WorkflowService,
)
from app.domains.documents.models import Document, DocumentStatus, DocumentType
from app.domains.export.models import ExportArtifact, ExportJob
from app.models.identity import Tenant, User
from app.models.projects import Project, ProjectMember


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


class CapturingStorage:
    """Storage fake that keeps uploaded export artifacts in memory."""

    def __init__(self):
        self.uploads = []

    async def upload(self, tenant_id, project_id, filename, content, content_type):
        self.uploads.append(
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "filename": filename,
                "content": content,
                "content_type": content_type,
            }
        )
        return SimpleNamespace(
            path=f"{tenant_id}/{project_id}/{filename}",
            filename=filename,
            content_type=content_type,
            size=len(content),
            hash="c" * 64,
            storage_backend="test",
        )


async def _seed_exportable_document(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()

    tenant = Tenant(id=tenant_id, name="Agent Export Tenant", slug="agent-export-tenant")
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email="agent-export@example.com",
        hashed_password="test",
        full_name="Agent Export Owner",
    )
    project = Project(
        id=project_id,
        tenant_id=tenant_id,
        owner_id=user_id,
        name="Agent Export Project",
        slug="agent-export-project",
    )
    member = ProjectMember(project_id=project_id, user_id=user_id)
    document = Document(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type=DocumentType.PRD.value,
        title="PRD Agent Export",
        content="# PRD Agent Export\n\n{{client_name}} delivery content.",
        status=DocumentStatus.PUBLISHED.value,
        version=1,
        created_by=user_id,
        metadata_json={},
    )
    db_session.add_all([tenant, user, project, member, document])
    await db_session.flush()
    return tenant_id, user_id, project_id, document


@pytest.mark.asyncio
async def test_builtin_skill_execution_returns_stable_display_envelope():
    result = await SkillService().execute_skill(
        "DocumentReviewer",
        {
            "content": "## Scope\n- The system validates every outbound order before shipment.",
            "review_type": "detailed",
        },
        {"document_type": "prd"},
    )

    assert set(["summary", "output", "evidence", "next_actions"]).issubset(result)
    assert result["summary"]
    assert result["output"]["score"] <= 1
    assert result["evidence"][0]["source"] == "builtin_skill"
    assert isinstance(result["next_actions"], list)


@pytest.mark.asyncio
async def test_export_orchestrator_creates_real_export_artifact(db_session, monkeypatch):
    tenant_id, user_id, _, document = await _seed_exportable_document(db_session)
    storage = CapturingStorage()
    monkeypatch.setattr("app.domains.export.service.get_storage_provider", lambda: storage)

    result = await SkillService(db_session).execute_skill(
        "ExportOrchestrator",
        {
            "document_id": str(document.id),
            "format": "markdown",
            "variables": {"client_name": "远大客户"},
        },
        {"tenant_id": tenant_id, "created_by": user_id},
    )

    assert result["success"] is True
    assert UUID(result["job_id"])
    assert result["file_size"] > 0
    assert result["artifact_count"] == 1
    assert result["artifacts"][0]["download_url"].endswith("/download")
    assert storage.uploads[0]["content_type"] == "text/markdown"
    assert "远大客户 delivery content" in storage.uploads[0]["content"].decode("utf-8")

    jobs = (await db_session.execute(select(ExportJob))).scalars().all()
    artifacts = (await db_session.execute(select(ExportArtifact))).scalars().all()
    assert len(jobs) == 1
    assert len(artifacts) == 1


@pytest.mark.asyncio
async def test_dag_executor_runs_document_export_tool_node(db_session, monkeypatch):
    tenant_id, user_id, project_id, document = await _seed_exportable_document(db_session)
    storage = CapturingStorage()
    monkeypatch.setattr("app.domains.export.service.get_storage_provider", lambda: storage)

    run = await AgentRunService(db_session).create_run(
        tenant_id=tenant_id,
        project_id=project_id,
        run_type="workflow",
        input_data={"document_id": str(document.id), "format": "markdown"},
    )
    dag_json = {
        "nodes": [
            {
                "id": "export",
                "type": "tool",
                "tool": "document_export",
                "config": {
                    "document_id": str(document.id),
                    "format": "markdown",
                    "variables": {"client_name": "远大客户"},
                },
            }
        ]
    }
    await AgentRunService(db_session).create_tasks_for_dag(
        run_id=run.id,
        tenant_id=tenant_id,
        dag_json=dag_json,
        input_data=run.input_data,
    )

    result = await DAGExecutor(db_session).execute_workflow(
        run.id,
        dag_json,
        run.input_data,
        {"tenant_id": tenant_id, "created_by": user_id},
    )

    assert result["success"] is True
    tasks = await AgentRunService(db_session).get_run_tasks(run.id, tenant_id)
    assert tasks[0].status == "completed"
    tool_output = tasks[0].output_data["tool_output"]
    assert tool_output["success"] is True
    assert tool_output["data"]["artifact_count"] == 1
    assert storage.uploads[0]["filename"].endswith(".md")


@pytest.mark.asyncio
async def test_catalog_skill_test_creates_direct_run_task_and_events(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()

    catalog = SkillCatalogService(db_session)
    await catalog.ensure_builtin_skills(tenant_id, user_id)

    skill = (
        await db_session.execute(
            select(AgentSkill).where(
                AgentSkill.tenant_id == tenant_id,
                AgentSkill.name == "DocumentReviewer",
            )
        )
    ).scalar_one()

    result = await catalog.test_skill(
        skill.id,
        tenant_id,
        {
            "content": "## Scope\n- Validate every outbound order before shipment.",
            "review_type": "quick",
        },
        {"project_id": str(project_id), "created_by": str(user_id)},
    )

    assert result["success"] is True
    assert UUID(result["run_id"])
    assert UUID(result["task_id"])
    assert result["output_data"]["summary"]

    run = await AgentRunService(db_session).get_run(UUID(result["run_id"]), tenant_id)
    assert run.run_type == "direct_skill"
    assert run.project_id == project_id
    assert run.status == "completed"
    assert run.metadata_json["execution_kind"] == "direct_skill"
    assert run.metadata_json["skill_name"] == "DocumentReviewer"

    tasks = await AgentRunService(db_session).get_run_tasks(run.id, tenant_id)
    assert len(tasks) == 1
    assert tasks[0].status == "completed"
    assert tasks[0].skill_name == "DocumentReviewer"
    assert tasks[0].output_data["execution"]["duration_ms"] >= 0
    assert tasks[0].output_data["result"]["summary"]

    events = await AgentRunService(db_session).get_run_events(run.id, tenant_id)
    assert [event.event_type for event in events] == [
        "direct_skill_started",
        "skill_task_started",
        "skill_task_completed",
        "direct_skill_completed",
    ]


@pytest.mark.asyncio
async def test_agent_profile_run_executes_bound_skill_and_records_failure_for_missing_skills(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()

    catalog = SkillCatalogService(db_session)
    await catalog.ensure_builtin_skills(tenant_id, user_id)
    reviewer = (
        await db_session.execute(
            select(AgentSkill).where(
                AgentSkill.tenant_id == tenant_id,
                AgentSkill.name == "DocumentReviewer",
            )
        )
    ).scalar_one()

    profile = await AgentProfileService(db_session).create_agent_profile(
        tenant_id=tenant_id,
        created_by=user_id,
        data=AgentProfileCreate(
            name="Runtime Reviewer",
            agent_type="quality",
            skill_ids=[reviewer.id],
        ),
    )

    run = await AgentRunService(db_session).execute_agent_profile_run(
        tenant_id=tenant_id,
        project_id=project_id,
        agent_profile_id=profile.id,
        input_data={
            "content": "## Scope\n- Validate every outbound order before shipment.",
            "review_type": "quick",
        },
        created_by=user_id,
    )

    assert run.status == "completed"
    assert run.run_type == "agent_profile"
    assert run.agent_profile_id == profile.id
    assert run.metadata_json["skill_name"] == "DocumentReviewer"

    tasks = await AgentRunService(db_session).get_run_tasks(run.id, tenant_id)
    assert len(tasks) == 1
    assert tasks[0].output_data["result"]["summary"]

    empty_profile = AgentProfile(
        tenant_id=tenant_id,
        name="Empty Agent",
        agent_type="quality",
        applicable_doc_types=[],
        tool_names=[],
        status="active",
        created_by=user_id,
    )
    db_session.add(empty_profile)
    await db_session.flush()

    with pytest.raises(ValueError, match="has no bound skills"):
        await AgentRunService(db_session).execute_agent_profile_run(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_profile_id=empty_profile.id,
            input_data={"content": "No skills can run"},
            created_by=user_id,
        )


@pytest.mark.asyncio
async def test_dag_executor_completes_workflow_run_with_task_evidence(db_session):
    tenant_id = uuid4()
    project_id = uuid4()

    run = await AgentRunService(db_session).create_run(
        tenant_id=tenant_id,
        project_id=project_id,
        run_type="workflow",
        input_data={
            "content": "## Scope\n- Validate every outbound order before shipment.",
            "review_type": "quick",
        },
    )
    dag_json = {
        "nodes": [
            {
                "id": "review",
                "type": "skill",
                "skill": "DocumentReviewer",
                "config": {"review_type": "quick"},
            }
        ]
    }
    await AgentRunService(db_session).create_tasks_for_dag(
        run_id=run.id,
        tenant_id=tenant_id,
        dag_json=dag_json,
        input_data=run.input_data,
    )

    result = await DAGExecutor(db_session).execute_workflow(
        run.id,
        dag_json,
        run.input_data,
        {"tenant_id": tenant_id},
    )

    assert result["success"] is True
    refreshed = await AgentRunService(db_session).get_run(run.id, tenant_id)
    assert refreshed.status == "completed"
    assert refreshed.metadata_json["execution_kind"] == "workflow"
    assert refreshed.metadata_json["completed_nodes"] == ["review"]

    task = (await AgentRunService(db_session).get_run_tasks(run.id, tenant_id))[0]
    assert task.status == "completed"
    assert task.output_data["skill_output"]["summary"]
    assert task.output_data["execution"]["duration_ms"] >= 0

    event_types = [
        event.event_type
        for event in (
            await db_session.execute(
                select(AgentEvent).where(AgentEvent.agent_run_id == run.id)
            )
        ).scalars()
    ]
    assert "workflow_started" in event_types
    assert "workflow_completed" in event_types


@pytest.mark.asyncio
async def test_run_list_and_detail_responses_include_runtime_summaries(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()

    workflow_service = WorkflowService(db_session)
    workflow = await workflow_service.create_workflow(
        tenant_id=tenant_id,
        name="PRD Runtime Workflow",
        description="Create and review PRD output",
        category="document_generation",
        created_by=user_id,
    )
    version = await workflow_service.create_version(
        workflow_id=workflow.id,
        tenant_id=tenant_id,
        dag_json={
            "nodes": [
                {"id": "review", "type": "skill", "skill": "DocumentReviewer"},
                {
                    "id": "export",
                    "type": "skill",
                    "skill": "ExportOrchestrator",
                    "depends_on": ["review"],
                },
            ]
        },
        skill_contracts=[],
        tool_contracts=[],
        created_by=user_id,
    )

    run_service = AgentRunService(db_session)
    run = await run_service.create_run(
        tenant_id=tenant_id,
        project_id=project_id,
        workflow_version_id=version.id,
        input_data={"content": "Draft PRD"},
    )
    await run_service.create_tasks_for_dag(
        run_id=run.id,
        tenant_id=tenant_id,
        dag_json=version.dag_json,
        input_data=run.input_data,
    )
    tasks = await run_service.get_run_tasks(run.id, tenant_id)
    await run_service.update_task_status(tasks[0].id, "completed", output_data={"summary": "Reviewed"})
    await run_service.update_task_status(tasks[1].id, "failed", error_message="Export target missing")
    await run_service.update_run_status(run.id, tenant_id, "failed", error_message="Export target missing")
    await run_service.log_event(
        run_id=run.id,
        tenant_id=tenant_id,
        event_type="workflow_failed",
        event_data={"code": "task_failed", "failed_node": "export"},
    )

    listed, total = await run_service.list_runs(tenant_id=tenant_id)
    detail = await run_service.get_run(run.id, tenant_id)

    assert total == 1
    list_response = AgentRunResponse.model_validate(listed[0])
    detail_response = AgentRunResponse.model_validate(detail)

    for response in [list_response, detail_response]:
        assert response.workflow is not None
        assert response.workflow.workflow_definition_id == workflow.id
        assert response.workflow.workflow_name == "PRD Runtime Workflow"
        assert response.workflow.version_id == version.id
        assert response.workflow.version == 1
        assert response.task_summary.total == 2
        assert response.task_summary.completed == 1
        assert response.task_summary.failed == 1
        assert response.event_summary.total == 1
        assert response.event_summary.last_event_type == "workflow_failed"
        assert response.duration_ms is not None
        assert response.progress_percent == 50
        assert response.can_retry is True
        assert response.can_cancel is False


@pytest.mark.asyncio
async def test_agent_profile_run_response_exposes_profile_summary_and_cancel_eligibility(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()

    catalog = SkillCatalogService(db_session)
    await catalog.ensure_builtin_skills(tenant_id, user_id)
    reviewer = (
        await db_session.execute(
            select(AgentSkill).where(
                AgentSkill.tenant_id == tenant_id,
                AgentSkill.name == "DocumentReviewer",
            )
        )
    ).scalar_one()

    profile = await AgentProfileService(db_session).create_agent_profile(
        tenant_id=tenant_id,
        created_by=user_id,
        data=AgentProfileCreate(
            name="Cancelable Reviewer",
            agent_type="quality",
            applicable_doc_types=["prd"],
            skill_ids=[reviewer.id],
        ),
    )

    run = await AgentRunService(db_session).create_run(
        tenant_id=tenant_id,
        project_id=project_id,
        agent_profile_id=profile.id,
        run_type="agent_profile",
        input_data={"content": "Pending review"},
    )
    await AgentRunService(db_session).submit_task(
        run_id=run.id,
        tenant_id=tenant_id,
        node_id="agent:DocumentReviewer",
        skill_name="DocumentReviewer",
        input_data=run.input_data,
    )
    await AgentRunService(db_session).log_event(
        run_id=run.id,
        tenant_id=tenant_id,
        event_type="agent_run_queued",
        event_data={"agent_profile_id": str(profile.id)},
    )

    response = AgentRunResponse.model_validate(
        await AgentRunService(db_session).get_run(run.id, tenant_id)
    )

    assert response.agent_profile is not None
    assert response.agent_profile.id == profile.id
    assert response.agent_profile.name == "Cancelable Reviewer"
    assert response.agent_profile.agent_type == "quality"
    assert response.task_summary.total == 1
    assert response.task_summary.pending == 1
    assert response.progress_percent == 0
    assert response.can_cancel is True
    assert response.can_retry is False


@pytest.mark.asyncio
async def test_default_workflows_are_seeded_for_first_run_lists(db_session):
    tenant_id = uuid4()
    user_id = uuid4()

    workflows, total = await WorkflowService(db_session).list_workflows(
        tenant_id=tenant_id,
        created_by=user_id,
        limit=100,
    )

    assert total >= 3
    assert {workflow.category for workflow in workflows} >= {
        "document_generation",
        "quality_assessment",
        "export_orchestration",
    }
    assert all(workflow.version_count >= 1 for workflow in workflows)


@pytest.mark.asyncio
async def test_workflow_templates_create_publishable_tenant_workflow(db_session):
    tenant_id = uuid4()
    user_id = uuid4()

    templates = WorkflowService.list_workflow_templates()

    assert {template["template_id"] for template in templates} >= {
        "brd-document-generation",
        "document-quality-assessment",
        "delivery-export-orchestration",
        "change-impact-governance",
    }
    assert all(template["display_name"] for template in templates)
    assert all(template["node_count"] >= len(template["skill_names"]) for template in templates)

    service = WorkflowService(db_session)
    workflow = await service.create_workflow_from_template(
        tenant_id=tenant_id,
        created_by=user_id,
        template_id="change-impact-governance",
    )

    assert workflow.name == "变更影响治理流水线"
    assert workflow.category == "requirement_analysis"
    assert workflow.version_count == 1

    version = (
        await db_session.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_definition_id == workflow.id,
                WorkflowVersion.is_active == 1,
            )
        )
    ).scalar_one()
    assert [node["skill"] for node in version.dag_json["nodes"]] == [
        "ChangeImpactAnalyzer",
        "PRDTraceabilityMapper",
        "TestCaseDesigner",
    ]

    duplicate = await service.create_workflow_from_template(
        tenant_id=tenant_id,
        created_by=user_id,
        template_id="change-impact-governance",
    )

    assert duplicate.name == "变更影响治理流水线 (2)"


@pytest.mark.asyncio
async def test_workflow_production_preflight_reports_gate_checks_and_run_evidence(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()

    workflow_service = WorkflowService(db_session)
    workflow = await workflow_service.create_workflow_from_template(
        tenant_id=tenant_id,
        created_by=user_id,
        template_id="change-impact-governance",
    )
    version = (
        await db_session.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_definition_id == workflow.id,
                WorkflowVersion.is_active == 1,
            )
        )
    ).scalar_one()

    run_service = AgentRunService(db_session)
    run = await run_service.create_run(
        tenant_id=tenant_id,
        project_id=project_id,
        workflow_version_id=version.id,
        input_data={"source": "preflight-test"},
    )
    await run_service.update_run_status(run.id, tenant_id, "completed")

    preflight = await workflow_service.get_workflow_production_preflight(
        workflow_id=workflow.id,
        tenant_id=tenant_id,
        project_id=project_id,
        input_data={"project_id": str(project_id)},
    )

    assert preflight is not None
    assert preflight["release_gate"]["status"] == "passed"
    assert preflight["release_gate"]["blockers"] == []
    assert preflight["preview"]["valid"] is True
    assert preflight["preview"]["estimated_steps"] >= 3
    assert preflight["active_version_id"] == version.id
    assert preflight["recent_runs"][0].id == run.id
    assert {check["code"] for check in preflight["checks"]} >= {
        "workflow_enabled",
        "active_version",
        "dag_valid",
        "project_context",
        "successful_run_evidence",
    }


@pytest.mark.asyncio
async def test_workflow_production_preflight_blocks_missing_project_context(db_session):
    tenant_id = uuid4()
    user_id = uuid4()

    workflow = await WorkflowService(db_session).create_workflow_from_template(
        tenant_id=tenant_id,
        created_by=user_id,
        template_id="document-quality-assessment",
    )

    preflight = await WorkflowService(db_session).get_workflow_production_preflight(
        workflow_id=workflow.id,
        tenant_id=tenant_id,
        project_id=None,
        input_data={},
    )

    assert preflight is not None
    assert preflight["release_gate"]["status"] == "blocked"
    assert "缺少项目上下文" in preflight["release_gate"]["blockers"]
    assert any(action["code"] == "missing_project_context" for action in preflight["next_actions"])


@pytest.mark.asyncio
async def test_orchestration_dashboard_seeds_defaults_and_reports_recovery_actions(db_session):
    tenant_id = uuid4()
    user_id = uuid4()

    run_service = AgentRunService(db_session)
    failed_run = await run_service.create_run(
        tenant_id=tenant_id,
        project_id=uuid4(),
        run_type="workflow",
        input_data={"content": "Draft PRD"},
    )
    await run_service.update_run_status(
        failed_run.id,
        tenant_id,
        "failed",
        error_message="Export target missing",
    )

    dashboard = await run_service.get_orchestration_dashboard(
        tenant_id=tenant_id,
        created_by=user_id,
    )

    assert dashboard["readiness_score"] >= 80
    assert dashboard["kpis"]["published_skills"] > 0
    assert dashboard["kpis"]["active_agents"] > 0
    assert dashboard["kpis"]["active_workflows"] >= 4
    assert dashboard["kpis"]["executable_workflows"] >= 4
    assert dashboard["kpis"]["failed_runs"] == 1
    assert dashboard["kpis"]["recoverable_runs"] == 1
    assert dashboard["run_status_counts"]["failed"] == 1
    assert dashboard["template_count"] >= 4
    assert dashboard["recent_runs"][0].id == failed_run.id
    assert any(issue["code"] == "recoverable_runs" for issue in dashboard["recommendations"])


@pytest.mark.asyncio
async def test_orchestration_bootstrap_initializes_callable_agents_skills_and_workflows(db_session):
    tenant_id = uuid4()
    user_id = uuid4()

    bootstrap = await AgentRunService(db_session).bootstrap_orchestration(
        tenant_id=tenant_id,
        created_by=user_id,
    )

    assert bootstrap["initialized"]["published_skills"] > 0
    assert bootstrap["initialized"]["active_agents"] >= 4
    assert bootstrap["initialized"]["active_workflows"] >= 4
    assert bootstrap["initialized"]["executable_agents"] == bootstrap["initialized"]["active_agents"]
    assert bootstrap["dashboard"]["kpis"]["published_skills"] == bootstrap["initialized"]["published_skills"]

    agents = (
        await db_session.scalars(
            select(AgentProfile).where(
                AgentProfile.tenant_id == tenant_id,
                AgentProfile.status == "active",
                AgentProfile.deleted_at.is_(None),
            )
        )
    ).all()
    workflows = (
        await db_session.scalars(
            select(WorkflowDefinition).where(
                WorkflowDefinition.tenant_id == tenant_id,
                WorkflowDefinition.is_active == 1,
                WorkflowDefinition.deleted_at.is_(None),
            )
        )
    ).all()

    assert workflows
    assert agents
    assert all(agent.workflow_definition_id is not None for agent in agents)


@pytest.mark.asyncio
async def test_create_tasks_for_dag_reports_structured_validation_errors(db_session):
    tenant_id = uuid4()
    run = await AgentRunService(db_session).create_run(
        tenant_id=tenant_id,
        project_id=uuid4(),
        input_data={},
    )

    with pytest.raises(ValueError) as exc_info:
        await AgentRunService(db_session).create_tasks_for_dag(
            run_id=run.id,
            tenant_id=tenant_id,
            dag_json={"nodes": [{"type": "skill", "skill": "DocumentReviewer"}]},
            input_data={},
        )

    error = exc_info.value.args[0]
    assert error["code"] == "invalid_workflow_dag"
    assert error["issues"][0]["message"] == "Node at index 0 is missing id"


@pytest.mark.asyncio
async def test_create_tasks_for_dag_tracks_mature_control_nodes(db_session):
    tenant_id = uuid4()
    run = await AgentRunService(db_session).create_run(
        tenant_id=tenant_id,
        project_id=uuid4(),
        input_data={"risk": "high"},
    )

    dag_json = {
        "nodes": [
            {"id": "draft", "type": "skill", "skill": "BRDWritePipeline"},
            {
                "id": "approval",
                "type": "human_approval",
                "depends_on": ["draft"],
                "config": {
                    "approval_title": "Approve controlled release",
                    "approver_role": "delivery_owner",
                },
            },
            {
                "id": "branch",
                "type": "condition",
                "depends_on": ["approval"],
                "config": {"expression": "input.risk == 'high'"},
            },
            {
                "id": "fanout",
                "type": "parallel_group",
                "depends_on": ["branch"],
                "config": {"branches": ["quality", "wait"]},
            },
            {"id": "quality", "type": "skill", "skill": "DocumentReviewer", "depends_on": ["fanout"]},
            {"id": "wait", "type": "delay", "depends_on": ["fanout"], "config": {"duration_seconds": 60}},
        ]
    }

    tasks = await AgentRunService(db_session).create_tasks_for_dag(
        run_id=run.id,
        tenant_id=tenant_id,
        dag_json=dag_json,
        input_data=run.input_data,
    )

    assert [task.node_id for task in tasks] == ["draft", "approval", "branch", "fanout", "quality", "wait"]
    control_task = next(task for task in tasks if task.node_id == "approval")
    assert control_task.skill_name is None
    assert control_task.input_data["node_type"] == "human_approval"
    assert control_task.input_data["control_metadata"]["approver_role"] == "delivery_owner"


@pytest.mark.asyncio
async def test_dag_executor_processes_control_nodes_and_run_hints(db_session):
    tenant_id = uuid4()
    run = await AgentRunService(db_session).create_run(
        tenant_id=tenant_id,
        project_id=uuid4(),
        run_type="workflow",
        input_data={"risk": "high"},
    )
    dag_json = {
        "nodes": [
            {
                "id": "approval",
                "type": "human_approval",
                "config": {
                    "approval_title": "Approve release",
                    "approver_role": "delivery_owner",
                },
            },
            {
                "id": "branch",
                "type": "condition",
                "depends_on": ["approval"],
                "config": {"expression": "input.risk == 'high'"},
            },
            {
                "id": "delay",
                "type": "delay",
                "depends_on": ["branch"],
                "config": {"duration_seconds": 5},
            },
        ]
    }
    await AgentRunService(db_session).create_tasks_for_dag(
        run_id=run.id,
        tenant_id=tenant_id,
        dag_json=dag_json,
        input_data=run.input_data,
    )

    result = await DAGExecutor(db_session).execute_workflow(
        run.id,
        dag_json,
        run.input_data,
        {"tenant_id": tenant_id},
    )

    assert result["success"] is False
    assert result["requires_human_action"] is True
    assert result["paused_node"] == "approval"
    tasks = await AgentRunService(db_session).get_run_tasks(run.id, tenant_id)
    assert tasks[0].status == "running"
    assert tasks[0].output_data["control_node"]["type"] == "human_approval"
    assert tasks[1].status == "pending"

    events = await AgentRunService(db_session).get_run_events(run.id, tenant_id)
    event_types = [event.event_type for event in events]
    assert "human_approval_required" in event_types
    assert "workflow_paused_for_control" in event_types
    assert "condition_evaluated" not in event_types

    response = AgentRunResponse.model_validate(
        await AgentRunService(db_session).get_run(run.id, tenant_id)
    )
    assert response.gate_summary["approval_gates"] == 1
    assert response.requires_human_action is True
    assert response.can_resume is False
    assert response.status_hint == "requires_human_approval"

    approved_run = await AgentRunService(db_session).apply_control_action(
        run_id=run.id,
        tenant_id=tenant_id,
        action="approve",
        actor_id=uuid4(),
        node_id="approval",
        comment="Approved for release",
    )

    approved_response = AgentRunResponse.model_validate(approved_run)
    assert approved_response.requires_human_action is False
    assert approved_response.can_resume is True
    assert approved_response.status_hint == "control_resolved"

    resumed = await DAGExecutor(db_session).execute_workflow(
        run.id,
        dag_json,
        run.input_data,
        {"tenant_id": tenant_id},
    )

    assert resumed["success"] is True
    tasks = await AgentRunService(db_session).get_run_tasks(run.id, tenant_id)
    assert all(task.status == "completed" for task in tasks)
    events = await AgentRunService(db_session).get_run_events(run.id, tenant_id)
    event_types = [event.event_type for event in events]
    assert "control_approve" in event_types
    assert "condition_evaluated" in event_types
    assert "delay_scheduled" in event_types


@pytest.mark.asyncio
async def test_condition_node_routes_only_selected_branch_and_skips_unselected_branch(db_session):
    tenant_id = uuid4()
    run = await AgentRunService(db_session).create_run(
        tenant_id=tenant_id,
        project_id=uuid4(),
        run_type="workflow",
        input_data={
            "risk": "high",
            "content": "## Scope\n- High risk warehouse release requires detailed review.",
        },
    )
    dag_json = {
        "nodes": [
            {
                "id": "branch",
                "type": "condition",
                "config": {
                    "expression": "input.risk == 'high'",
                    "paths": [
                        {"label": "high_risk", "target": "high_review"},
                        {"label": "standard", "target": "standard_review"},
                    ],
                },
            },
            {
                "id": "high_review",
                "type": "skill",
                "skill": "DocumentReviewer",
                "depends_on": ["branch"],
            },
            {
                "id": "standard_review",
                "type": "skill",
                "skill": "ExportOrchestrator",
                "depends_on": ["branch"],
            },
            {
                "id": "merge",
                "type": "merge",
                "depends_on": ["high_review", "standard_review"],
            },
        ]
    }
    await AgentRunService(db_session).create_tasks_for_dag(
        run_id=run.id,
        tenant_id=tenant_id,
        dag_json=dag_json,
        input_data=run.input_data,
    )

    result = await DAGExecutor(db_session).execute_workflow(
        run.id,
        dag_json,
        run.input_data,
        {"tenant_id": tenant_id},
    )

    assert result["success"] is True
    tasks = {task.node_id: task for task in await AgentRunService(db_session).get_run_tasks(run.id, tenant_id)}
    assert tasks["high_review"].status == "completed"
    assert tasks["high_review"].output_data["skill_output"]["summary"]
    assert tasks["standard_review"].status == "completed"
    assert tasks["standard_review"].output_data["status"] == "skipped"
    assert tasks["standard_review"].output_data["skip_reason"] == "condition_unselected"
    assert tasks["merge"].output_data["merged_outputs"]["high_review"]["skill_output"]["summary"]
    assert tasks["merge"].output_data["merged_outputs"]["standard_review"]["status"] == "skipped"

    events = await AgentRunService(db_session).get_run_events(run.id, tenant_id)
    event_types = [event.event_type for event in events]
    assert "condition_routed" in event_types
    assert "node_skipped" in event_types


@pytest.mark.asyncio
async def test_parallel_group_executes_configured_branches_concurrently_and_merges_outputs(db_session):
    tenant_id = uuid4()
    run = await AgentRunService(db_session).create_run(
        tenant_id=tenant_id,
        project_id=uuid4(),
        run_type="workflow",
        input_data={"content": "Parallel review input"},
    )
    dag_json = {
        "nodes": [
            {
                "id": "fanout",
                "type": "parallel_group",
                "config": {"branches": ["left_review", "right_review"]},
            },
            {
                "id": "left_review",
                "type": "skill",
                "skill": "LeftReviewSkill",
                "depends_on": ["fanout"],
            },
            {
                "id": "right_review",
                "type": "skill",
                "skill": "RightReviewSkill",
                "depends_on": ["fanout"],
            },
            {
                "id": "merge",
                "type": "merge",
                "depends_on": ["left_review", "right_review"],
            },
        ]
    }
    await AgentRunService(db_session).create_tasks_for_dag(
        run_id=run.id,
        tenant_id=tenant_id,
        dag_json=dag_json,
        input_data=run.input_data,
    )
    executor = DAGExecutor(db_session)
    call_windows = []

    async def fake_execute_skill(skill_name, input_data, context):
        started_at = time.perf_counter()
        await asyncio.sleep(0.1)
        completed_at = time.perf_counter()
        call_windows.append((skill_name, started_at, completed_at))
        return {
            "summary": f"{skill_name} completed",
            "output": {"skill_name": skill_name},
            "evidence": [],
            "next_actions": [],
        }

    executor.skill_service.execute_skill = fake_execute_skill
    started = time.perf_counter()
    result = await executor.execute_workflow(
        run.id,
        dag_json,
        run.input_data,
        {"tenant_id": tenant_id},
    )
    elapsed = time.perf_counter() - started

    assert result["success"] is True
    assert elapsed < 2
    assert len(call_windows) == 2
    first, second = sorted(call_windows, key=lambda item: item[1])
    assert second[1] < first[2]
    tasks = {task.node_id: task for task in await AgentRunService(db_session).get_run_tasks(run.id, tenant_id)}
    assert tasks["left_review"].output_data["skill_output"]["summary"] == "LeftReviewSkill completed"
    assert tasks["right_review"].output_data["skill_output"]["summary"] == "RightReviewSkill completed"
    assert tasks["merge"].output_data["merged_outputs"]["left_review"]["skill_output"]["summary"] == "LeftReviewSkill completed"
    assert tasks["merge"].output_data["merged_outputs"]["right_review"]["skill_output"]["summary"] == "RightReviewSkill completed"

    events = await AgentRunService(db_session).get_run_events(run.id, tenant_id)
    assert "parallel_group_completed" in [event.event_type for event in events]


@pytest.mark.asyncio
async def test_blocking_delay_node_pauses_until_explicit_resume_then_runs_downstream(db_session):
    tenant_id = uuid4()
    run = await AgentRunService(db_session).create_run(
        tenant_id=tenant_id,
        project_id=uuid4(),
        run_type="workflow",
        input_data={"content": "Delay release input"},
    )
    dag_json = {
        "nodes": [
            {
                "id": "wait",
                "type": "delay",
                "config": {"duration_seconds": 60, "blocking": True},
            },
            {
                "id": "export",
                "type": "skill",
                "skill": "DocumentReviewer",
                "depends_on": ["wait"],
            },
        ]
    }
    await AgentRunService(db_session).create_tasks_for_dag(
        run_id=run.id,
        tenant_id=tenant_id,
        dag_json=dag_json,
        input_data=run.input_data,
    )

    first = await DAGExecutor(db_session).execute_workflow(
        run.id,
        dag_json,
        run.input_data,
        {"tenant_id": tenant_id},
    )

    assert first["success"] is False
    assert first["requires_delay"] is True
    assert first["paused_node"] == "wait"
    paused_run = AgentRunResponse.model_validate(
        await AgentRunService(db_session).get_run(run.id, tenant_id)
    )
    assert paused_run.status == "pending"
    assert paused_run.status_hint == "delay_scheduled"
    assert paused_run.can_resume is True
    assert paused_run.metadata_json["resume_after"]

    tasks = {task.node_id: task for task in await AgentRunService(db_session).get_run_tasks(run.id, tenant_id)}
    assert tasks["wait"].status == "running"
    assert tasks["export"].status == "pending"

    await AgentRunService(db_session).apply_control_action(
        run_id=run.id,
        tenant_id=tenant_id,
        action="resume",
        actor_id=uuid4(),
        node_id="wait",
        comment="Delay window elapsed in test",
    )
    resumed = await DAGExecutor(db_session).execute_workflow(
        run.id,
        dag_json,
        run.input_data,
        {"tenant_id": tenant_id},
    )

    assert resumed["success"] is True
    tasks = {task.node_id: task for task in await AgentRunService(db_session).get_run_tasks(run.id, tenant_id)}
    assert tasks["wait"].status == "completed"
    assert tasks["wait"].output_data["control_action"] == "resume"
    assert tasks["export"].status == "completed"


@pytest.mark.asyncio
async def test_merge_node_collects_dependency_outputs_with_source_metadata(db_session):
    tenant_id = uuid4()
    run = await AgentRunService(db_session).create_run(
        tenant_id=tenant_id,
        project_id=uuid4(),
        run_type="workflow",
        input_data={"content": "Merge evidence input"},
    )
    dag_json = {
        "nodes": [
            {"id": "review", "type": "skill", "skill": "DocumentReviewer"},
            {"id": "mece", "type": "skill", "skill": "MECEAnalyzer"},
            {"id": "merge", "type": "merge", "depends_on": ["review", "mece"]},
        ]
    }
    await AgentRunService(db_session).create_tasks_for_dag(
        run_id=run.id,
        tenant_id=tenant_id,
        dag_json=dag_json,
        input_data=run.input_data,
    )

    result = await DAGExecutor(db_session).execute_workflow(
        run.id,
        dag_json,
        run.input_data,
        {"tenant_id": tenant_id},
    )

    assert result["success"] is True
    tasks = {task.node_id: task for task in await AgentRunService(db_session).get_run_tasks(run.id, tenant_id)}
    merge_output = tasks["merge"].output_data
    assert merge_output["control_node"]["type"] == "merge"
    assert merge_output["merge_strategy"] == "collect"
    assert merge_output["source_nodes"] == ["review", "mece"]
    assert merge_output["merged_outputs"]["review"]["skill_output"]["summary"]
    assert merge_output["merged_outputs"]["mece"]["skill_output"]["summary"]


@pytest.mark.asyncio
async def test_list_runs_filters_by_workflow_identity_and_search_text(db_session):
    tenant_id = uuid4()
    actor_id = uuid4()
    project_id = uuid4()
    workflow_service = WorkflowService(db_session)
    run_service = AgentRunService(db_session)

    workflow = await workflow_service.create_workflow(
        tenant_id=tenant_id,
        name="PRD review production workflow",
        description="Filterable workflow for operations",
        category="document_review",
        created_by=actor_id,
    )
    version = await workflow_service.create_version(
        workflow_id=workflow.id,
        tenant_id=tenant_id,
        dag_json={"nodes": [{"id": "review", "type": "skill", "skill": "DocumentReviewer"}]},
        skill_contracts=[],
        tool_contracts=[],
        created_by=actor_id,
    )
    await workflow_service.activate_version(version.id, tenant_id)

    matching_run = await run_service.create_run(
        tenant_id=tenant_id,
        project_id=project_id,
        workflow_version_id=version.id,
        input_data={
            "workflow_name": "PRD review production workflow",
            "case": "priority release",
        },
    )
    await run_service.log_event(
        run_id=matching_run.id,
        tenant_id=tenant_id,
        event_type="run_queued",
        event_data={"workflow_id": str(workflow.id)},
    )

    other_workflow = await workflow_service.create_workflow(
        tenant_id=tenant_id,
        name="Export release workflow",
        description="Should not be returned",
        category="export_orchestration",
        created_by=actor_id,
    )
    other_version = await workflow_service.create_version(
        workflow_id=other_workflow.id,
        tenant_id=tenant_id,
        dag_json={"nodes": [{"id": "export", "type": "skill", "skill": "ExportOrchestrator"}]},
        skill_contracts=[],
        tool_contracts=[],
        created_by=actor_id,
    )
    await run_service.create_run(
        tenant_id=tenant_id,
        project_id=project_id,
        workflow_version_id=other_version.id,
        input_data={"workflow_name": "Export release workflow", "case": "standard release"},
    )

    runs, total = await run_service.list_runs(
        tenant_id=tenant_id,
        workflow_definition_id=workflow.id,
        run_type="workflow",
        search="priority",
        skip=0,
        limit=20,
    )

    assert total == 1
    assert [run.id for run in runs] == [matching_run.id]
    response = AgentRunResponse.model_validate(runs[0])
    assert response.workflow is not None
    assert response.workflow.workflow_definition_id == workflow.id
    assert response.event_summary.total == 1
