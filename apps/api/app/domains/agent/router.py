"""Agent Runtime API Router

Endpoints for workflow management, agent runs, tasks, and skill execution.
"""

import inspect
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import decode_token
from app.models.identity import User
from app.domains.agent.models import (
    WorkflowDefinition,
    WorkflowVersion,
    AgentRun,
    AgentTask,
    AgentRunStatus,
)
from app.domains.agent.schemas import (
    SkillCatalogCreate,
    SkillCatalogUpdate,
    SkillCatalogResponse,
    SkillCatalogListResponse,
    OrchestrationBootstrapResponse,
    OrchestrationDashboardResponse,
    AgentProfileCreate,
    AgentProfileUpdate,
    AgentProfileResponse,
    AgentProfileListResponse,
    AgentSkillBindingUpdate,
    WorkflowDefinitionCreate,
    WorkflowDefinitionUpdate,
    WorkflowFromTemplateCreate,
    WorkflowDefinitionResponse,
    WorkflowDefinitionListResponse,
    WorkflowTemplateResponse,
    WorkflowTemplateListResponse,
    WorkflowVersionCreate,
    WorkflowVersionResponse,
    WorkflowVersionListResponse,
    WorkflowVersionActivateResponse,
    AgentRunCreate,
    AgentRunResponse,
    AgentRunControlActionRequest,
    AgentRunStatusUpdate,
    AgentRunListResponse,
    AgentTaskResponse,
    AgentTaskListResponse,
    AgentEventResponse,
    AgentEventListResponse,
    AgentRunActionResponse,
    WorkflowDAGValidateRequest,
    DAGValidationResponse,
    WorkflowDAGPreviewRequest,
    WorkflowDAGPreviewResponse,
    WorkflowProductionPreflightResponse,
    SkillExecuteRequest,
    SkillExecuteResponse,
    SkillCatalogTestRequest,
    SkillCatalogTestResponse,
    SkillInfoResponse,
    SkillListResponse,
    WorkflowExecuteRequest,
    WorkflowExecuteResponse,
    PaginationParams,
)
from app.domains.agent.service import (
    SkillCatalogService,
    AgentProfileService,
    WorkflowService,
    AgentRunService,
    SkillService,
    DAGExecutor,
)


router = APIRouter()


async def enqueue_workflow_run_job(run_id: UUID) -> None:
    """Enqueue workflow execution through ARQ.

    ARQ does not expose the old top-level ``enqueue_job`` helper in current
    versions. The supported flow is to create an ``ArqRedis`` pool and call
    ``enqueue_job`` on that pool.
    """
    from arq import create_pool
    from app.workers.redis_config import arq_redis_settings

    redis = await create_pool(arq_redis_settings())

    try:
        await redis.enqueue_job("execute_workflow_run", str(run_id))
    finally:
        close = getattr(redis, "aclose", None) or getattr(redis, "close", None)
        if close is not None:
            close_result = close()
            if inspect.isawaitable(close_result):
                await close_result


async def get_current_user(
    authorization: str = Header(..., description="Bearer token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency to get current authenticated user.

    Args:
        authorization: Bearer token header
        db: Database session

    Returns:
        User: Current authenticated user

    Raises:
        HTTPException: If token is invalid or user not found
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization[7:]

    try:
        from app.domains.identity.service import AuthService

        auth_service = AuthService(db)
        user = await auth_service.get_current_user(token)

        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        return user
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


# ============ Orchestration Cockpit Endpoints ============


@router.get("/orchestration/dashboard", response_model=OrchestrationDashboardResponse)
async def get_orchestration_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a production cockpit snapshot for intelligent orchestration."""
    service = AgentRunService(db)
    dashboard = await service.get_orchestration_dashboard(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
    )
    return OrchestrationDashboardResponse.model_validate(dashboard)


@router.post("/orchestration/bootstrap", response_model=OrchestrationBootstrapResponse)
async def bootstrap_orchestration(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Explicitly initialize built-in skills, default agents, and workflows."""
    service = AgentRunService(db)
    result = await service.bootstrap_orchestration(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
    )
    return OrchestrationBootstrapResponse.model_validate(result)


# ============ Skill Marketplace Endpoints ============


@router.get("/skills/catalog", response_model=SkillCatalogListResponse)
async def list_skill_catalog(
    skill_type: str | None = Query(None, description="Filter by skill type"),
    status: str | None = Query(None, description="Filter by status"),
    doc_type: str | None = Query(None, description="Filter by supported document type"),
    search: str | None = Query(None, description="Search name, description, or category"),
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List tenant skill marketplace entries, including seeded built-ins."""
    service = SkillCatalogService(db)
    skills, total = await service.list_skills(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        skill_type=skill_type,
        status=status,
        doc_type=doc_type,
        search=search,
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
    )

    return SkillCatalogListResponse(
        items=[SkillCatalogResponse.model_validate(skill) for skill in skills],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=(pagination.page * pagination.page_size) < total,
    )


@router.post("/skills/catalog", response_model=SkillCatalogResponse, status_code=201)
async def create_skill_catalog_entry(
    data: SkillCatalogCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a custom skill entry in the marketplace."""
    service = SkillCatalogService(db)
    try:
        skill = await service.create_skill(
            tenant_id=current_user.tenant_id,
            created_by=current_user.id,
            data=data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SkillCatalogResponse.model_validate(skill)


@router.patch("/skills/catalog/{skill_id}", response_model=SkillCatalogResponse)
async def update_skill_catalog_entry(
    skill_id: UUID,
    data: SkillCatalogUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update skill catalog metadata."""
    service = SkillCatalogService(db)
    try:
        skill = await service.update_skill(skill_id, current_user.tenant_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillCatalogResponse.model_validate(skill)


@router.post("/skills/catalog/{skill_id}/publish", response_model=SkillCatalogResponse)
async def publish_skill_catalog_entry(
    skill_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Publish a draft skill."""
    service = SkillCatalogService(db)
    try:
        skill = await service.set_skill_status(skill_id, current_user.tenant_id, "published")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillCatalogResponse.model_validate(skill)


@router.post("/skills/catalog/{skill_id}/disable", response_model=SkillCatalogResponse)
async def disable_skill_catalog_entry(
    skill_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable a skill without deleting historical bindings."""
    service = SkillCatalogService(db)
    try:
        skill = await service.set_skill_status(skill_id, current_user.tenant_id, "disabled")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillCatalogResponse.model_validate(skill)


@router.post("/skills/catalog/{skill_id}/test", response_model=SkillCatalogTestResponse)
async def test_skill_catalog_entry(
    skill_id: UUID,
    data: SkillCatalogTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Validate and test a catalog skill against its input contract."""
    service = SkillCatalogService(db)
    context = dict(data.context or {})
    if data.project_id:
        context["project_id"] = str(data.project_id)
    context.setdefault("created_by", str(current_user.id))
    try:
        result = await service.test_skill(
            skill_id=skill_id,
            tenant_id=current_user.tenant_id,
            input_data=data.input_data,
            context=context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    skill = result["skill"]
    return SkillCatalogTestResponse(
        skill_id=skill.id,
        skill_name=skill.name,
        success=result["success"],
        output_data=result["output_data"],
        error_message=result["error_message"],
        execution_time_ms=result["execution_time_ms"],
        mode=result["mode"],
        run_id=result.get("run_id"),
        task_id=result.get("task_id"),
    )


# ============ Agent Profile Endpoints ============


@router.get("", response_model=AgentProfileListResponse)
@router.get("/", response_model=AgentProfileListResponse)
@router.get("/agent-profiles", response_model=AgentProfileListResponse)
async def list_agent_profiles(
    agent_type: str | None = Query(None, description="Filter by agent type"),
    status: str | None = Query(None, description="Filter by status"),
    doc_type: str | None = Query(None, description="Filter by document type"),
    search: str | None = Query(None, description="Search name or description"),
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List configurable agent profiles."""
    service = AgentProfileService(db)
    profiles, total = await service.list_agent_profiles(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        agent_type=agent_type,
        status=status,
        doc_type=doc_type,
        search=search,
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
    )

    return AgentProfileListResponse(
        items=[AgentProfileResponse.model_validate(profile) for profile in profiles],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=(pagination.page * pagination.page_size) < total,
    )


@router.post("/agent-profiles", response_model=AgentProfileResponse, status_code=201)
async def create_agent_profile(
    data: AgentProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an agent profile with ordered skill bindings."""
    service = AgentProfileService(db)
    try:
        profile = await service.create_agent_profile(
            tenant_id=current_user.tenant_id,
            created_by=current_user.id,
            data=data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AgentProfileResponse.model_validate(profile)


@router.get("/agent-profiles/{agent_profile_id}", response_model=AgentProfileResponse)
async def get_agent_profile(
    agent_profile_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get an agent profile."""
    service = AgentProfileService(db)
    profile = await service.get_agent_profile(agent_profile_id, current_user.tenant_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    return AgentProfileResponse.model_validate(profile)


@router.patch("/agent-profiles/{agent_profile_id}", response_model=AgentProfileResponse)
async def update_agent_profile(
    agent_profile_id: UUID,
    data: AgentProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an agent profile."""
    service = AgentProfileService(db)
    try:
        profile = await service.update_agent_profile(
            agent_profile_id,
            current_user.tenant_id,
            data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not profile:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    return AgentProfileResponse.model_validate(profile)


@router.put("/agent-profiles/{agent_profile_id}/skills", response_model=AgentProfileResponse)
async def replace_agent_profile_skills(
    agent_profile_id: UUID,
    data: AgentSkillBindingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace ordered skill bindings for an agent profile."""
    service = AgentProfileService(db)
    profile = await service.get_agent_profile(agent_profile_id, current_user.tenant_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    try:
        await service.replace_skill_bindings(
            agent_profile_id,
            current_user.tenant_id,
            data.skill_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    refreshed = await service.get_agent_profile(agent_profile_id, current_user.tenant_id)
    return AgentProfileResponse.model_validate(refreshed)


@router.post("/agent-profiles/{agent_profile_id}/activate", response_model=AgentProfileResponse)
async def activate_agent_profile(
    agent_profile_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Activate an agent profile."""
    service = AgentProfileService(db)
    profile = await service.set_agent_status(agent_profile_id, current_user.tenant_id, "active")
    if not profile:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    return AgentProfileResponse.model_validate(profile)


@router.post("/agent-profiles/{agent_profile_id}/disable", response_model=AgentProfileResponse)
async def disable_agent_profile(
    agent_profile_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable an agent profile."""
    service = AgentProfileService(db)
    profile = await service.set_agent_status(agent_profile_id, current_user.tenant_id, "disabled")
    if not profile:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    return AgentProfileResponse.model_validate(profile)


# ============ Workflow Definition Endpoints ============


@router.get("/workflows", response_model=WorkflowDefinitionListResponse)
async def list_workflows(
    category: str | None = Query(None, description="Filter by category"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all workflow definitions for the current tenant.

    Args:
        category: Optional category filter
        is_active: Optional active filter
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of workflow definitions
    """
    service = WorkflowService(db)
    workflows, total = await service.list_workflows(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        category=category,
        is_active=is_active,
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
    )
    has_more = (pagination.page * pagination.page_size) < total

    return WorkflowDefinitionListResponse(
        items=[WorkflowDefinitionResponse.model_validate(w) for w in workflows],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=has_more,
    )


@router.get("/workflows/templates", response_model=WorkflowTemplateListResponse)
async def list_workflow_templates(
    current_user: User = Depends(get_current_user),
):
    """List platform workflow templates available for tenant cloning."""
    templates = WorkflowService.list_workflow_templates()
    return WorkflowTemplateListResponse(
        items=[WorkflowTemplateResponse.model_validate(template) for template in templates],
        total=len(templates),
    )


@router.post(
    "/workflows/from-template",
    response_model=WorkflowDefinitionResponse,
    status_code=201,
)
async def create_workflow_from_template(
    data: WorkflowFromTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create and optionally publish a workflow from a platform template."""
    service = WorkflowService(db)
    try:
        workflow = await service.create_workflow_from_template(
            tenant_id=current_user.tenant_id,
            created_by=current_user.id,
            template_id=data.template_id,
            name=data.name,
            description=data.description,
            publish=data.publish,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WorkflowDefinitionResponse.model_validate(workflow)


@router.post("/workflows", response_model=WorkflowDefinitionResponse, status_code=201)
async def create_workflow(
    data: WorkflowDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new workflow definition.

    Args:
        data: Workflow creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created workflow definition
    """
    service = WorkflowService(db)
    workflow = await service.create_workflow(
        tenant_id=current_user.tenant_id,
        name=data.name,
        description=data.description,
        category=data.category,
        created_by=current_user.id,
    )
    return WorkflowDefinitionResponse.model_validate(workflow)


@router.get("/workflows/{workflow_id}", response_model=WorkflowDefinitionResponse)
async def get_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a workflow definition by ID.

    Args:
        workflow_id: Workflow UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Workflow definition details

    Raises:
        HTTPException: If workflow not found
    """
    service = WorkflowService(db)
    workflow = await service.get_workflow(workflow_id, current_user.tenant_id)

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return WorkflowDefinitionResponse.model_validate(workflow)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowDefinitionResponse)
async def update_workflow(
    workflow_id: UUID,
    data: WorkflowDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a workflow definition.

    Args:
        workflow_id: Workflow UUID
        data: Update data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated workflow definition

    Raises:
        HTTPException: If workflow not found
    """
    service = WorkflowService(db)
    workflow = await service.update_workflow(
        workflow_id=workflow_id,
        tenant_id=current_user.tenant_id,
        updates=data,
    )

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return WorkflowDefinitionResponse.model_validate(workflow)


@router.delete("/workflows/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a workflow definition (soft delete).

    Args:
        workflow_id: Workflow UUID
        db: Database session
        current_user: Current authenticated user

    Raises:
        HTTPException: If workflow not found
    """
    service = WorkflowService(db)
    deleted = await service.delete_workflow(workflow_id, current_user.tenant_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")


@router.post("/workflows/validate", response_model=DAGValidationResponse)
async def validate_workflow_dag_endpoint(
    data: WorkflowDAGValidateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Validate workflow DAG shape and skill bindings before saving a version."""
    service = WorkflowService(db)
    validation = await service.validate_dag(current_user.tenant_id, data.dag_json)
    return DAGValidationResponse.model_validate(validation)


@router.post("/workflows/preview", response_model=WorkflowDAGPreviewResponse)
async def preview_workflow_dag_endpoint(
    data: WorkflowDAGPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Preview workflow execution order, gates, and blocking preflight issues."""
    service = WorkflowService(db)
    preview = await service.preview_dag(
        current_user.tenant_id,
        data.dag_json,
        data.input_data,
    )
    return WorkflowDAGPreviewResponse.model_validate(preview)


@router.get(
    "/workflows/{workflow_id}/production-preflight",
    response_model=WorkflowProductionPreflightResponse,
)
async def get_workflow_production_preflight(
    workflow_id: UUID,
    project_id: UUID | None = Query(None, description="Project context for execution readiness"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Inspect whether a concrete workflow is ready for production execution."""
    service = WorkflowService(db)
    preflight = await service.get_workflow_production_preflight(
        workflow_id=workflow_id,
        tenant_id=current_user.tenant_id,
        project_id=project_id,
        input_data={
            "project_id": str(project_id) if project_id else None,
            "source": "workflow_production_preflight",
        },
    )
    if preflight is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowProductionPreflightResponse.model_validate(preflight)


# ============ Workflow Version Endpoints ============


@router.post(
    "/workflows/{workflow_id}/versions",
    response_model=WorkflowVersionResponse,
    status_code=201,
)
async def create_version(
    workflow_id: UUID,
    data: WorkflowVersionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new workflow version.

    Args:
        workflow_id: Workflow UUID
        data: Version creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created workflow version

    Raises:
        HTTPException: If workflow not found
    """
    service = WorkflowService(db)

    # Convert skill/tool contracts to dicts
    skill_contracts = [s.model_dump() for s in data.skill_contracts] if data.skill_contracts else []
    tool_contracts = [t.model_dump() for t in data.tool_contracts] if data.tool_contracts else []

    try:
        version = await service.create_version(
            workflow_id=workflow_id,
            tenant_id=current_user.tenant_id,
            dag_json=data.dag_json,
            skill_contracts=skill_contracts,
            tool_contracts=tool_contracts,
            created_by=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not version:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return WorkflowVersionResponse.model_validate(version)


@router.get("/workflows/{workflow_id}/versions", response_model=WorkflowVersionListResponse)
async def list_versions(
    workflow_id: UUID,
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all versions of a workflow.

    Args:
        workflow_id: Workflow UUID
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of workflow versions

    Raises:
        HTTPException: If workflow not found
    """
    service = WorkflowService(db)
    workflow = await service.get_workflow(workflow_id, current_user.tenant_id)

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    versions = sorted(workflow.versions, key=lambda v: v.version, reverse=True)
    total = len(versions)
    skip = (pagination.page - 1) * pagination.page_size
    paginated_versions = versions[skip : skip + pagination.page_size]

    return WorkflowVersionListResponse(
        items=[WorkflowVersionResponse.model_validate(v) for v in paginated_versions],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=(pagination.page * pagination.page_size) < total,
    )


@router.get(
    "/workflows/{workflow_id}/versions/{version_id}",
    response_model=WorkflowVersionResponse,
)
async def get_version(
    workflow_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific workflow version.

    Args:
        workflow_id: Workflow UUID
        version_id: Version UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Workflow version details

    Raises:
        HTTPException: If version not found
    """
    service = WorkflowService(db)
    version = await service.get_version(version_id, current_user.tenant_id)

    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    if version.workflow_definition_id != workflow_id:
        raise HTTPException(status_code=404, detail="Version does not belong to this workflow")

    return WorkflowVersionResponse.model_validate(version)


@router.post(
    "/workflows/{workflow_id}/versions/{version_id}/activate",
    response_model=WorkflowVersionActivateResponse,
)
async def activate_version(
    workflow_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Activate a workflow version.

    Args:
        workflow_id: Workflow UUID
        version_id: Version UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Activation result

    Raises:
        HTTPException: If version not found
    """
    service = WorkflowService(db)
    version = await service.activate_version(version_id, current_user.tenant_id)

    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    if version.workflow_definition_id != workflow_id:
        raise HTTPException(status_code=404, detail="Version does not belong to this workflow")

    return WorkflowVersionActivateResponse(
        version_id=version.id,
        workflow_definition_id=version.workflow_definition_id,
        is_active=bool(version.is_active),
        message="Version activated successfully",
    )


# ============ Agent Run Endpoints ============


@router.get("/agent-runs", response_model=AgentRunListResponse)
async def list_runs(
    project_id: UUID | None = Query(None, description="Filter by project ID"),
    status: str | None = Query(None, description="Filter by status"),
    run_type: str | None = Query(None, description="Filter by run type"),
    workflow_definition_id: UUID | None = Query(None, description="Filter by workflow definition ID"),
    workflow_version_id: UUID | None = Query(None, description="Filter by workflow version ID"),
    agent_profile_id: UUID | None = Query(None, description="Filter by agent profile ID"),
    search: str | None = Query(None, description="Search run input, metadata, error, or ID"),
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all agent runs for the current tenant.

    Args:
        project_id: Optional project filter
        status: Optional status filter
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of agent runs
    """
    service = AgentRunService(db)
    runs, total = await service.list_runs(
        tenant_id=current_user.tenant_id,
        project_id=project_id,
        status=status,
        run_type=run_type,
        workflow_definition_id=workflow_definition_id,
        workflow_version_id=workflow_version_id,
        agent_profile_id=agent_profile_id,
        search=search,
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
    )
    has_more = (pagination.page * pagination.page_size) < total

    return AgentRunListResponse(
        items=[AgentRunResponse.model_validate(r) for r in runs],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=has_more,
    )


@router.post("/agent-runs", response_model=WorkflowExecuteResponse, status_code=201)
async def create_run(
    data: AgentRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new agent run (workflow execution).

    Args:
        data: Run creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Run creation response with run ID
    """
    service = AgentRunService(db)
    workflow_service = WorkflowService(db)

    if data.agent_profile_id:
        try:
            run = await service.execute_agent_profile_run(
                tenant_id=current_user.tenant_id,
                project_id=data.project_id,
                agent_profile_id=data.agent_profile_id,
                input_data=data.input_data,
                created_by=current_user.id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return WorkflowExecuteResponse(
            run_id=run.id,
            status=run.status,
            message="Agent profile run executed",
        )

    # Get workflow version
    workflow_version_id = data.workflow_version_id
    if not workflow_version_id:
        # Use active version from the workflow
        # For now, we need the workflow_id from somewhere
        # This would typically come from the request or a linked entity
        raise HTTPException(
            status_code=400,
            detail="workflow_version_id is required",
        )

    # Verify version exists
    version = await workflow_service.get_version(workflow_version_id, current_user.tenant_id)
    if not version:
        raise HTTPException(status_code=404, detail="Workflow version not found")

    # Create the run
    run = await service.create_run(
        tenant_id=current_user.tenant_id,
        project_id=data.project_id,
        workflow_version_id=workflow_version_id,
        created_by=current_user.id,
        input_data=data.input_data,
    )

    return WorkflowExecuteResponse(
        run_id=run.id,
        status=run.status,
        message="Agent run created successfully",
    )


@router.get("/agent-runs/{run_id}", response_model=AgentRunResponse)
async def get_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get an agent run by ID.

    Args:
        run_id: AgentRun UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Agent run details

    Raises:
        HTTPException: If run not found
    """
    service = AgentRunService(db)
    run = await service.get_run(run_id, current_user.tenant_id)

    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    return AgentRunResponse.model_validate(run)


@router.patch("/agent-runs/{run_id}/status", response_model=AgentRunResponse)
async def update_run_status(
    run_id: UUID,
    data: AgentRunStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update agent run status.

    Args:
        run_id: AgentRun UUID
        data: Status update data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated agent run

    Raises:
        HTTPException: If run not found
    """
    service = AgentRunService(db)
    run = await service.update_run_status(
        run_id=run_id,
        tenant_id=current_user.tenant_id,
        status=data.status,
        error_message=data.error_message,
    )

    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    return AgentRunResponse.model_validate(run)


@router.get("/agent-runs/{run_id}/tasks", response_model=AgentTaskListResponse)
async def get_run_tasks(
    run_id: UUID,
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all tasks for an agent run.

    Args:
        run_id: AgentRun UUID
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of agent tasks

    Raises:
        HTTPException: If run not found
    """
    service = AgentRunService(db)

    # Verify run exists
    run = await service.get_run(run_id, current_user.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    tasks = await service.get_run_tasks(run_id, current_user.tenant_id)
    total = len(tasks)
    skip = (pagination.page - 1) * pagination.page_size
    paginated_tasks = tasks[skip : skip + pagination.page_size]

    return AgentTaskListResponse(
        items=[AgentTaskResponse.model_validate(t) for t in paginated_tasks],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=(pagination.page * pagination.page_size) < total,
    )


@router.get("/agent-runs/{run_id}/events", response_model=AgentEventListResponse)
async def get_run_events(
    run_id: UUID,
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get audit events for an agent run."""
    service = AgentRunService(db)
    run = await service.get_run(run_id, current_user.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    events = await service.get_run_events(run_id, current_user.tenant_id)
    total = len(events)
    skip = (pagination.page - 1) * pagination.page_size
    paginated_events = events[skip : skip + pagination.page_size]

    return AgentEventListResponse(
        items=[AgentEventResponse.model_validate(event) for event in paginated_events],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=(pagination.page * pagination.page_size) < total,
    )


@router.post("/agent-runs/{run_id}/cancel", response_model=AgentRunResponse)
async def cancel_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel a pending or running agent run."""
    service = AgentRunService(db)
    try:
        run = await service.cancel_run(run_id, current_user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return AgentRunResponse.model_validate(run)


@router.post("/agent-runs/{run_id}/retry", response_model=AgentRunActionResponse)
async def retry_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reset and enqueue a failed or cancelled workflow run."""
    service = AgentRunService(db)
    try:
        run = await service.prepare_run_retry(run_id, current_user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    try:
        await enqueue_workflow_run_job(run.id)
    except Exception as e:
        await service.update_run_status(
            run_id=run.id,
            tenant_id=current_user.tenant_id,
            status="failed",
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=f"Failed to queue workflow: {str(e)}")

    return AgentRunActionResponse(
        run_id=run.id,
        status=run.status,
        message="Workflow retry queued successfully",
    )


@router.post("/agent-runs/{run_id}/control-actions", response_model=AgentRunResponse)
async def apply_run_control_action(
    run_id: UUID,
    data: AgentRunControlActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resolve a workflow control node such as human approval, resume, or reject."""
    service = AgentRunService(db)
    try:
        run = await service.apply_control_action(
            run_id=run_id,
            tenant_id=current_user.tenant_id,
            action=data.action,
            actor_id=current_user.id,
            node_id=data.node_id,
            comment=data.comment,
            output_data=data.output_data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    if data.action.strip().lower() in {"approve", "resume", "skip"}:
        try:
            await enqueue_workflow_run_job(run.id)
        except Exception as e:
            await service.update_run_status(
                run_id=run.id,
                tenant_id=current_user.tenant_id,
                status="failed",
                error_message=str(e),
            )
            raise HTTPException(status_code=500, detail=f"Failed to queue workflow: {str(e)}")
        run = await service.get_run(run.id, current_user.tenant_id) or run

    return AgentRunResponse.model_validate(run)


# ============ Skills Endpoints ============


@router.get("/skills", response_model=SkillListResponse)
async def list_skills(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all available skills.

    Args:
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of available skills
    """
    service = SkillService(db)
    skills = service.list_skills()

    return SkillListResponse(
        skills=[
            SkillInfoResponse(
                name=s["name"],
                description=s["description"],
                input_schema=s["input_schema"],
                output_schema=s["output_schema"],
                is_builtin=s.get("is_builtin", False),
            )
            for s in skills
        ]
    )


@router.post("/skills/execute", response_model=SkillExecuteResponse)
async def execute_skill(
    data: SkillExecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute a skill.

    Args:
        data: Skill execution data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Skill execution result

    Raises:
        HTTPException: If skill not found or execution fails
    """
    import time

    service = SkillService(db)

    start_time = time.time()

    try:
        result = await service.execute_skill(
            skill_name=data.skill_name,
            input_data=data.input_data,
            context=data.context,
        )

        execution_time = (time.time() - start_time) * 1000

        return SkillExecuteResponse(
            success=True,
            output_data=result,
            execution_time_ms=round(execution_time, 2),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        execution_time = (time.time() - start_time) * 1000
        return SkillExecuteResponse(
            success=False,
            error_message=str(e),
            execution_time_ms=round(execution_time, 2),
        )


# ============ Workflow Execution Endpoint ============


@router.post("/workflows/execute", response_model=WorkflowExecuteResponse)
async def execute_workflow(
    data: WorkflowExecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute a workflow.

    Args:
        data: Workflow execution data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Workflow execution response

    Raises:
        HTTPException: If workflow or version not found
    """
    workflow_service = WorkflowService(db)
    run_service = AgentRunService(db)

    # Get workflow version
    version_id = data.version_id
    if not version_id:
        # Get active version
        active_version = await workflow_service.get_active_version(
            workflow_id=data.workflow_id,
            tenant_id=current_user.tenant_id,
        )
        if not active_version:
            raise HTTPException(status_code=400, detail="No active version found for workflow")
        version_id = active_version.id

    version = await workflow_service.get_version(version_id, current_user.tenant_id)
    if not version:
        raise HTTPException(status_code=404, detail="Workflow version not found")
    if version.workflow_definition_id != data.workflow_id:
        raise HTTPException(status_code=404, detail="Version does not belong to this workflow")

    validate_dag = getattr(workflow_service, "validate_dag", None)
    if validate_dag is not None:
        validation = await validate_dag(
            current_user.tenant_id,
            getattr(version, "dag_json", {}) or {},
        )
        if not validation["valid"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "invalid_workflow_dag",
                    "message": "Workflow DAG validation failed",
                    "issues": validation["issues"],
                },
            )

    # Create agent run
    run = await run_service.create_run(
        tenant_id=current_user.tenant_id,
        project_id=data.project_id,
        workflow_version_id=version_id,
        input_data=data.input_data,
    )

    create_tasks_for_dag = getattr(run_service, "create_tasks_for_dag", None)
    if create_tasks_for_dag is not None:
        try:
            await create_tasks_for_dag(
                run_id=run.id,
                tenant_id=current_user.tenant_id,
                dag_json=getattr(version, "dag_json", {}) or {},
                input_data=data.input_data,
            )
        except ValueError as exc:
            detail = exc.args[0] if exc.args and isinstance(exc.args[0], dict) else str(exc)
            await run_service.update_run_status(
                run_id=run.id,
                tenant_id=current_user.tenant_id,
                status="failed",
                error_message=str(detail),
            )
            raise HTTPException(status_code=400, detail=detail) from exc

    await run_service.log_event(
        run_id=run.id,
        tenant_id=current_user.tenant_id,
        event_type="run_queued",
        event_data={
            "workflow_id": str(data.workflow_id),
            "version_id": str(version_id),
            "input_data": data.input_data,
        },
    )

    # Enqueue ARQ job for execution
    try:
        await enqueue_workflow_run_job(run.id)
    except Exception as e:
        # Update run as failed
        await run_service.update_run_status(
            run_id=run.id,
            tenant_id=current_user.tenant_id,
            status="failed",
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=f"Failed to queue workflow: {str(e)}")

    return WorkflowExecuteResponse(
        run_id=run.id,
        status=run.status,
        message="Workflow execution queued successfully",
    )
