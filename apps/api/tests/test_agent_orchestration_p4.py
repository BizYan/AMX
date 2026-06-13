"""P4 agent orchestration API contracts."""

import os
from types import SimpleNamespace
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-agent-orchestration-p4.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-agent-orchestration-p4-secret"

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import pytest


@pytest.mark.asyncio
async def test_skill_marketplace_lists_seeded_builtin_skills(monkeypatch):
    from app.domains.agent import router as agent_router
    from app.domains.agent.schemas import PaginationParams
    from app.models.identity import User

    tenant_id = uuid4()
    user_id = uuid4()
    calls = []

    class MockSkillCatalogService:
        def __init__(self, db):
            pass

        async def list_skills(
            self,
            tenant_id,
            created_by,
            skill_type=None,
            status=None,
            doc_type=None,
            search=None,
            skip=0,
            limit=20,
        ):
            calls.append(
                {
                    "tenant_id": tenant_id,
                    "created_by": created_by,
                    "skill_type": skill_type,
                    "status": status,
                    "doc_type": doc_type,
                    "search": search,
                    "skip": skip,
                    "limit": limit,
                }
            )
            return [
                SimpleNamespace(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    name="DocumentReviewer",
                    description="Review documents for quality",
                    skill_type="quality",
                    category="builtin",
                    input_schema_json={"type": "object"},
                    output_schema_json={"type": "object"},
                    supported_doc_types=["prd"],
                    supported_industries=[],
                    version="1.0.0",
                    status="published",
                    is_builtin=1,
                    implementation_ref="builtin:DocumentReviewer",
                    metadata_json={},
                    created_by=user_id,
                    created_at=None,
                    updated_at=None,
                    deleted_at=None,
                )
            ], 1

    monkeypatch.setattr(agent_router, "SkillCatalogService", MockSkillCatalogService)

    response = await agent_router.list_skill_catalog(
        skill_type="quality",
        status="published",
        doc_type="prd",
        search="review",
        pagination=PaginationParams(page=1, page_size=20),
        db=None,
        current_user=User(id=user_id, tenant_id=tenant_id),
    )

    assert response.total == 1
    assert response.items[0].name == "DocumentReviewer"
    assert response.items[0].is_builtin is True
    assert calls == [
        {
            "tenant_id": tenant_id,
            "created_by": user_id,
            "skill_type": "quality",
            "status": "published",
            "doc_type": "prd",
            "search": "review",
            "skip": 0,
            "limit": 20,
        }
    ]


@pytest.mark.asyncio
async def test_agent_profile_create_binds_skills(monkeypatch):
    from app.domains.agent import router as agent_router
    from app.domains.agent.schemas import AgentProfileCreate
    from app.models.identity import User

    tenant_id = uuid4()
    user_id = uuid4()
    skill_id = uuid4()
    agent_id = uuid4()
    calls = []

    class MockAgentProfileService:
        def __init__(self, db):
            pass

        async def create_agent_profile(self, tenant_id, created_by, data):
            calls.append(("create", tenant_id, created_by, data.skill_ids))
            return SimpleNamespace(
                id=agent_id,
                tenant_id=tenant_id,
                name=data.name,
                description=data.description,
                agent_type=data.agent_type,
                applicable_doc_types=data.applicable_doc_types,
                default_template_id=data.default_template_id,
                tool_names=data.tool_names,
                workflow_definition_id=data.workflow_definition_id,
                human_review_required=1,
                status="active",
                system_prompt=data.system_prompt,
                created_by=user_id,
                created_at=None,
                updated_at=None,
                deleted_at=None,
                skill_bindings=[],
            )

    monkeypatch.setattr(agent_router, "AgentProfileService", MockAgentProfileService)

    response = await agent_router.create_agent_profile(
        data=AgentProfileCreate(
            name="PRD Agent",
            description="Drafts and reviews PRD documents",
            agent_type="prd",
            applicable_doc_types=["prd"],
            tool_names=["knowledge_graph"],
            skill_ids=[skill_id],
            system_prompt="Follow product requirements format.",
        ),
        db=None,
        current_user=User(id=user_id, tenant_id=tenant_id),
    )

    assert response.name == "PRD Agent"
    assert response.applicable_doc_types == ["prd"]
    assert calls == [("create", tenant_id, user_id, [skill_id])]


@pytest.mark.asyncio
async def test_execute_workflow_creates_agent_tasks_before_enqueue(monkeypatch):
    from app.domains.agent.router import execute_workflow
    from app.domains.agent.schemas import WorkflowExecuteRequest
    from app.models.identity import User

    version_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    run_id = uuid4()
    tenant_id = uuid4()
    created_tasks = []

    dag_json = {
        "nodes": [
            {"id": "clarify", "type": "skill", "skill": "RequirementClarifier"},
            {
                "id": "review",
                "type": "skill",
                "skill": "DocumentReviewer",
                "depends_on": ["clarify"],
            },
        ]
    }

    class MockWorkflowService:
        def __init__(self, db):
            pass

        async def get_version(self, version_id, tenant_id):
            return SimpleNamespace(
                id=version_id,
                workflow_definition_id=workflow_id,
                dag_json=dag_json,
            )

        async def get_active_version(self, workflow_id, tenant_id):
            return SimpleNamespace(id=version_id)

    class MockAgentRunService:
        def __init__(self, db):
            pass

        async def create_run(self, tenant_id, project_id, workflow_version_id, input_data=None):
            return SimpleNamespace(id=run_id, status="pending")

        async def create_tasks_for_dag(self, run_id, tenant_id, dag_json, input_data):
            created_tasks.append((run_id, tenant_id, dag_json, input_data))
            return []

        async def log_event(self, run_id, tenant_id, event_type, event_data):
            return SimpleNamespace(id=uuid4())

    monkeypatch.setattr("app.domains.agent.router.WorkflowService", MockWorkflowService)
    monkeypatch.setattr("app.domains.agent.router.AgentRunService", MockAgentRunService)

    enqueue_calls = []

    async def mock_enqueue(rid):
        enqueue_calls.append(rid)

    monkeypatch.setattr("app.domains.agent.router.enqueue_workflow_run_job", mock_enqueue)

    response = await execute_workflow(
        data=WorkflowExecuteRequest(
            workflow_id=workflow_id,
            version_id=version_id,
            project_id=project_id,
            input_data={"document_type": "prd"},
        ),
        db=None,
        current_user=User(id=uuid4(), tenant_id=tenant_id),
    )

    assert response.run_id == run_id
    assert enqueue_calls == [run_id]
    assert created_tasks == [(run_id, tenant_id, dag_json, {"document_type": "prd"})]


@pytest.mark.asyncio
async def test_execute_workflow_returns_structured_validation_error_before_run_creation(monkeypatch):
    from fastapi import HTTPException

    from app.domains.agent.router import execute_workflow
    from app.domains.agent.schemas import WorkflowExecuteRequest
    from app.models.identity import User

    version_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    tenant_id = uuid4()
    dag_json = {"nodes": [{"type": "skill", "skill": "MissingSkill"}]}

    class MockWorkflowService:
        def __init__(self, db):
            pass

        async def get_version(self, version_id, tenant_id):
            return SimpleNamespace(
                id=version_id,
                workflow_definition_id=workflow_id,
                dag_json=dag_json,
            )

        async def get_active_version(self, workflow_id, tenant_id):
            return SimpleNamespace(id=version_id)

        async def validate_dag(self, tenant_id, dag_json):
            return {
                "valid": False,
                "issues": [
                    {
                        "severity": "error",
                        "node_id": None,
                        "message": "Node at index 0 is missing id",
                    }
                ],
                "execution_order": [],
            }

    class MockAgentRunService:
        def __init__(self, db):
            pass

        async def create_run(self, *args, **kwargs):
            raise AssertionError("invalid workflow should not create an agent run")

    monkeypatch.setattr("app.domains.agent.router.WorkflowService", MockWorkflowService)
    monkeypatch.setattr("app.domains.agent.router.AgentRunService", MockAgentRunService)

    with pytest.raises(HTTPException) as exc_info:
        await execute_workflow(
            data=WorkflowExecuteRequest(
                workflow_id=workflow_id,
                version_id=version_id,
                project_id=project_id,
                input_data={"document_type": "prd"},
            ),
            db=None,
            current_user=User(id=uuid4(), tenant_id=tenant_id),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "invalid_workflow_dag"
    assert exc_info.value.detail["issues"][0]["message"] == "Node at index 0 is missing id"


def test_dag_validation_allows_forward_dependencies_and_rejects_cycles():
    from app.domains.agent.service import validate_workflow_dag

    valid = validate_workflow_dag(
        {
            "nodes": [
                {"id": "review", "type": "skill", "skill": "DocumentReviewer", "depends_on": ["clarify"]},
                {"id": "clarify", "type": "skill", "skill": "RequirementClarifier"},
            ]
        },
        {"DocumentReviewer", "RequirementClarifier"},
    )

    assert valid["valid"] is True
    assert valid["execution_order"] == ["clarify", "review"]

    cycle = validate_workflow_dag(
        {
            "nodes": [
                {"id": "a", "type": "skill", "depends_on": ["b"]},
                {"id": "b", "type": "skill", "depends_on": ["a"]},
            ]
        }
    )

    assert cycle["valid"] is False
    assert any("cycle" in issue["message"] for issue in cycle["issues"])


def test_mature_dag_validation_reports_control_node_contracts():
    from app.domains.agent.service import validate_workflow_dag

    validation = validate_workflow_dag(
        {
            "nodes": [
                {"id": "draft", "type": "skill", "skill": "BRDWritePipeline"},
                {
                    "id": "approval",
                    "type": "human_approval",
                    "depends_on": ["draft"],
                    "config": {"approval_title": "Approve delivery"},
                },
                {
                    "id": "branch",
                    "type": "condition",
                    "depends_on": ["approval"],
                    "config": {"paths": [{"label": "approved", "target": "fanout"}]},
                },
                {
                    "id": "fanout",
                    "type": "parallel_group",
                    "depends_on": ["branch"],
                    "config": {"branches": ["quality", "export"]},
                },
                {"id": "quality", "type": "skill", "skill": "DocumentReviewer", "depends_on": ["fanout"]},
                {"id": "export", "type": "delay", "depends_on": ["fanout"], "config": {"duration_seconds": 30}},
                {"id": "unknown", "type": "robot", "depends_on": ["missing"]},
            ]
        },
        {"BRDWritePipeline", "DocumentReviewer"},
    )

    assert validation["valid"] is False
    issues_by_code = {issue["code"]: issue for issue in validation["issues"]}
    assert issues_by_code["human_approval_missing_approver"]["node_id"] == "approval"
    assert issues_by_code["condition_missing_expression"]["node_id"] == "branch"
    assert issues_by_code["unknown_node_type"]["node_id"] == "unknown"
    assert issues_by_code["missing_dependency"]["node_id"] == "unknown"


def test_workflow_preview_contract_summarizes_runtime_gates():
    from app.domains.agent.service import build_workflow_execution_preview

    preview = build_workflow_execution_preview(
        {
            "nodes": [
                {"id": "draft", "type": "skill", "skill": "BRDWritePipeline"},
                {
                    "id": "approval",
                    "type": "human_approval",
                    "depends_on": ["draft"],
                    "config": {
                        "approval_title": "Approve delivery",
                        "approver_role": "delivery_owner",
                    },
                },
                {
                    "id": "branch",
                    "type": "condition",
                    "depends_on": ["approval"],
                    "config": {
                        "expression": "input.risk == 'high'",
                        "paths": [
                            {"label": "high", "target": "quality"},
                            {"label": "standard", "target": "export"},
                        ],
                    },
                },
                {
                    "id": "parallel",
                    "type": "parallel_group",
                    "depends_on": ["branch"],
                    "config": {"branches": ["quality", "export"]},
                },
                {"id": "quality", "type": "skill", "skill": "DocumentReviewer", "depends_on": ["parallel"]},
                {"id": "export", "type": "delay", "depends_on": ["parallel"], "config": {"duration_seconds": 10}},
            ]
        },
        {"risk": "high"},
        {"BRDWritePipeline", "DocumentReviewer"},
    )

    assert preview["execution_order"] == ["draft", "approval", "branch", "parallel", "quality", "export"]
    assert preview["estimated_steps"] == 6
    assert preview["approval_gates"][0]["node_id"] == "approval"
    assert preview["approval_gates"][0]["approver_role"] == "delivery_owner"
    assert preview["parallel_groups"][0]["branches"] == ["quality", "export"]
    assert preview["condition_paths"][0]["expression"] == "input.risk == 'high'"
    assert preview["blocking_issues"] == []


@pytest.mark.asyncio
async def test_workflow_preview_api_uses_service_contract(monkeypatch):
    from app.domains.agent import router as agent_router
    from app.domains.agent.schemas import WorkflowDAGPreviewRequest
    from app.models.identity import User

    tenant_id = uuid4()
    user_id = uuid4()
    calls = []

    class MockWorkflowService:
        def __init__(self, db):
            pass

        async def preview_dag(self, tenant_id, dag_json, input_data=None):
            calls.append((tenant_id, dag_json, input_data))
            return {
                "valid": True,
                "issues": [],
                "execution_order": ["draft", "approval"],
                "parallel_groups": [],
                "approval_gates": [{"node_id": "approval", "approver_role": "owner"}],
                "condition_paths": [],
                "estimated_steps": 2,
                "blocking_issues": [],
            }

    monkeypatch.setattr(agent_router, "WorkflowService", MockWorkflowService)

    response = await agent_router.preview_workflow_dag_endpoint(
        data=WorkflowDAGPreviewRequest(
            dag_json={"nodes": [{"id": "draft", "type": "skill", "skill": "BRDWritePipeline"}]},
            input_data={"document_type": "brd"},
        ),
        db=None,
        current_user=User(id=user_id, tenant_id=tenant_id),
    )

    assert response.execution_order == ["draft", "approval"]
    assert response.approval_gates[0]["node_id"] == "approval"
    assert calls == [
        (
            tenant_id,
            {"nodes": [{"id": "draft", "type": "skill", "skill": "BRDWritePipeline"}]},
            {"document_type": "brd"},
        )
    ]


def test_mature_workflow_templates_are_available():
    from app.domains.agent.service import WorkflowService

    templates = WorkflowService.list_workflow_templates()
    by_id = {template["template_id"]: template for template in templates}

    assert {
        "human-approval-delivery-pipeline",
        "conditional-requirement-governance",
        "parallel-quality-review",
    }.issubset(by_id)
    assert any(
        node["type"] == "human_approval"
        for node in by_id["human-approval-delivery-pipeline"]["dag_json"]["nodes"]
    )
    assert any(
        node["type"] == "condition"
        for node in by_id["conditional-requirement-governance"]["dag_json"]["nodes"]
    )
    assert any(
        node["type"] == "parallel_group"
        for node in by_id["parallel-quality-review"]["dag_json"]["nodes"]
    )


@pytest.mark.asyncio
async def test_skill_catalog_test_executes_builtin_skill(monkeypatch):
    from app.domains.agent import router as agent_router
    from app.domains.agent.schemas import SkillCatalogTestRequest
    from app.models.identity import User

    tenant_id = uuid4()
    user_id = uuid4()
    skill_id = uuid4()

    class MockSkillCatalogService:
        def __init__(self, db):
            pass

        async def test_skill(self, skill_id, tenant_id, input_data, context):
            return {
                "skill": SimpleNamespace(id=skill_id, name="DocumentReviewer"),
                "success": True,
                "output_data": {"score": 0.9},
                "error_message": None,
                "execution_time_ms": 1.2,
                "mode": "builtin",
            }

    monkeypatch.setattr(agent_router, "SkillCatalogService", MockSkillCatalogService)

    response = await agent_router.test_skill_catalog_entry(
        skill_id=skill_id,
        data=SkillCatalogTestRequest(input_data={"content": "A complete PRD draft"}),
        db=None,
        current_user=User(id=user_id, tenant_id=tenant_id),
    )

    assert response.skill_name == "DocumentReviewer"
    assert response.success is True
    assert response.mode == "builtin"
