"""Agent Runtime Domain Schemas

Pydantic v2 schemas for request/response validation in the agent runtime platform.
"""

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Generic type for paginated responses
T = TypeVar("T")


class PaginationParams(BaseModel):
    """Pagination parameters for list endpoints."""

    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response schema."""

    items: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool


class SkillCatalogCreate(BaseModel):
    """Create a custom skill catalog entry."""

    name: str = Field(..., min_length=1, max_length=255)
    display_name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    skill_type: str = Field(default="custom", max_length=50)
    category: str = Field(default="custom", max_length=100)
    input_schema_json: dict[str, Any] = Field(default_factory=dict)
    output_schema_json: dict[str, Any] = Field(default_factory=dict)
    supported_doc_types: list[str] = Field(default_factory=list)
    supported_industries: list[str] = Field(default_factory=list)
    version: str = Field(default="1.0.0", max_length=50)
    status: str = Field(default="draft")
    governance_scope: str = Field(default="tenant", max_length=30)
    visibility: str = Field(default="tenant", max_length=30)
    implementation_ref: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class SkillCatalogUpdate(BaseModel):
    """Update a skill catalog entry."""

    name: str | None = Field(None, min_length=1, max_length=255)
    display_name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    skill_type: str | None = Field(None, max_length=50)
    category: str | None = Field(None, max_length=100)
    input_schema_json: dict[str, Any] | None = None
    output_schema_json: dict[str, Any] | None = None
    supported_doc_types: list[str] | None = None
    supported_industries: list[str] | None = None
    version: str | None = Field(None, max_length=50)
    status: str | None = None
    governance_scope: str | None = Field(None, max_length=30)
    visibility: str | None = Field(None, max_length=30)
    implementation_ref: str | None = None
    metadata_json: dict[str, Any] | None = None


class SkillCatalogResponse(BaseModel):
    """Skill catalog response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    name: str
    display_name: str | None = None
    effective_display_name: str = ""
    description: str | None
    skill_type: str
    category: str
    input_schema_json: dict[str, Any]
    output_schema_json: dict[str, Any]
    supported_doc_types: list[str]
    supported_industries: list[str]
    version: str
    status: str
    is_builtin: bool
    governance_scope: str = "tenant"
    visibility: str = "tenant"
    managed_by: str = "tenant"
    is_locked: bool = False
    can_edit: bool = True
    can_publish: bool = True
    can_disable: bool = True
    locked_reason: str | None = None
    implementation_ref: str | None
    metadata_json: dict[str, Any]
    created_by: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    @model_validator(mode="after")
    def fill_display_defaults(self) -> "SkillCatalogResponse":
        """Keep response defaults stable for legacy rows and older tests."""
        if not self.effective_display_name:
            self.effective_display_name = self.display_name or self.name
        return self


class SkillCatalogListResponse(PaginatedResponse[SkillCatalogResponse]):
    """Paginated skill catalog response."""

    pass


class AgentSkillBindingResponse(BaseModel):
    """Agent skill binding response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    agent_profile_id: UUID
    skill_id: UUID
    order_index: int
    is_required: bool
    skill: SkillCatalogResponse | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentProfileCreate(BaseModel):
    """Create an agent profile."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    agent_type: str = Field(default="custom", max_length=50)
    applicable_doc_types: list[str] = Field(default_factory=list)
    default_template_id: UUID | None = None
    tool_names: list[str] = Field(default_factory=list)
    workflow_definition_id: UUID | None = None
    human_review_required: bool = True
    status: str = Field(default="active")
    system_prompt: str | None = None
    skill_ids: list[UUID] = Field(default_factory=list)


class AgentProfileUpdate(BaseModel):
    """Update an agent profile."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    agent_type: str | None = Field(None, max_length=50)
    applicable_doc_types: list[str] | None = None
    default_template_id: UUID | None = None
    tool_names: list[str] | None = None
    workflow_definition_id: UUID | None = None
    human_review_required: bool | None = None
    status: str | None = None
    system_prompt: str | None = None
    skill_ids: list[UUID] | None = None


class AgentSkillBindingUpdate(BaseModel):
    """Replace agent skill bindings."""

    skill_ids: list[UUID] = Field(default_factory=list)


class AgentProfileResponse(BaseModel):
    """Agent profile response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    name: str
    description: str | None
    agent_type: str
    applicable_doc_types: list[str]
    default_template_id: UUID | None
    tool_names: list[str]
    workflow_definition_id: UUID | None
    human_review_required: bool
    status: str
    system_prompt: str | None
    created_by: UUID
    skill_bindings: list[AgentSkillBindingResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None


class AgentProfileListResponse(PaginatedResponse[AgentProfileResponse]):
    """Paginated agent profile response."""

    pass


# SkillContract Schema
class SkillContractSchema(BaseModel):
    """Schema for skill contract definition."""

    name: str = Field(..., description="Skill name")
    description: str = Field(..., description="Skill description")
    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema for skill input",
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema for skill output",
    )


# ToolContract Schema
class ToolContractSchema(BaseModel):
    """Schema for tool contract definition."""

    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema for tool input",
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema for tool output",
    )


# DAG Node Schema
class DAGNodeSchema(BaseModel):
    """Schema for a node in the workflow DAG."""

    id: str = Field(..., description="Node unique identifier")
    type: str = Field(..., description="Node type (skill, tool, etc.)")
    skill: str | None = Field(None, description="Skill name to execute")
    tool: str | None = Field(None, description="Tool name to use")
    depends_on: list[str] = Field(
        default_factory=list,
        description="List of node IDs this node depends on",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Node configuration",
    )


# DAG Schema
class DAGSchema(BaseModel):
    """Schema for workflow DAG definition."""

    nodes: list[DAGNodeSchema] = Field(
        default_factory=list,
        description="List of nodes in the DAG",
    )


# WorkflowDefinition Schemas
class WorkflowDefinitionCreate(BaseModel):
    """Schema for creating a workflow definition."""

    name: str = Field(..., min_length=1, max_length=255, description="Workflow name")
    description: str | None = Field(None, description="Workflow description")
    category: str = Field(
        default="custom",
        description="Workflow category",
    )


class WorkflowFromTemplateCreate(BaseModel):
    """Create and optionally publish a workflow from a platform template."""

    template_id: str = Field(..., min_length=1, max_length=100)
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    publish: bool = True


class WorkflowDefinitionUpdate(BaseModel):
    """Schema for updating a workflow definition."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None
    is_active: bool | None = None


class WorkflowDefinitionResponse(BaseModel):
    """Schema for workflow definition response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    name: str
    description: str | None
    category: str
    version_count: int
    is_active: bool
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class WorkflowDefinitionListResponse(PaginatedResponse[WorkflowDefinitionResponse]):
    """Schema for paginated workflow definition list response."""

    pass


class WorkflowTemplateResponse(BaseModel):
    """Platform workflow template available for tenant cloning."""

    template_id: str
    name: str
    display_name: str
    description: str
    category: str
    dag_json: dict[str, Any]
    node_count: int = 0
    skill_names: list[str] = Field(default_factory=list)
    recommended_doc_types: list[str] = Field(default_factory=list)
    readiness_checks: list[str] = Field(default_factory=list)


class WorkflowTemplateListResponse(BaseModel):
    """Workflow template list response."""

    items: list[WorkflowTemplateResponse]
    total: int


# WorkflowVersion Schemas
class WorkflowVersionCreate(BaseModel):
    """Schema for creating a workflow version."""

    dag_json: dict[str, Any] = Field(
        default_factory=dict,
        description="DAG definition as JSON",
    )
    skill_contracts: list[SkillContractSchema] = Field(
        default_factory=list,
        description="List of skill contracts",
    )
    tool_contracts: list[ToolContractSchema] = Field(
        default_factory=list,
        description="List of tool contracts",
    )


class WorkflowVersionResponse(BaseModel):
    """Schema for workflow version response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_definition_id: UUID
    version: int
    dag_json: dict[str, Any]
    skill_contracts_json: list[dict[str, Any]]
    tool_contracts_json: list[dict[str, Any]]
    is_active: bool
    created_by: UUID
    created_at: datetime


class WorkflowVersionListResponse(PaginatedResponse[WorkflowVersionResponse]):
    """Schema for paginated workflow version list response."""

    pass


# AgentRun Schemas
class AgentRunCreate(BaseModel):
    """Schema for creating an agent run."""

    project_id: UUID | None = Field(
        None,
        description="Optional project ID; required for workflow runs, optional for direct agent-profile runs",
    )
    agent_profile_id: UUID | None = Field(
        None,
        description="Agent profile ID for direct agent-profile execution",
    )
    workflow_version_id: UUID | None = Field(
        None,
        description="Workflow version ID (uses active version if not provided)",
    )
    workflow_id: UUID | None = Field(
        None,
        description="Workflow definition ID used to resolve the active version when workflow_version_id is omitted",
    )
    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Input data for the workflow",
    )


class AgentRunStatusUpdate(BaseModel):
    """Schema for updating agent run status."""

    status: str = Field(
        ...,
        description="New status (pending, running, completed, failed, cancelled)",
    )
    error_message: str | None = Field(None, description="Error message if failed")


class AgentRunAgentProfileSummary(BaseModel):
    """Compact agent profile data embedded in run responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    agent_type: str
    status: str
    applicable_doc_types: list[str] = Field(default_factory=list)


class AgentRunWorkflowSummary(BaseModel):
    """Compact workflow data embedded in run responses."""

    version_id: UUID
    workflow_definition_id: UUID
    workflow_name: str | None = None
    category: str | None = None
    version: int | None = None
    is_active: bool = False


class AgentRunTaskSummary(BaseModel):
    """Task aggregate for run list/detail responses."""

    total: int = 0
    pending: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    last_task_id: UUID | None = None
    last_task_status: str | None = None
    last_error_message: str | None = None


class AgentRunEventSummary(BaseModel):
    """Event aggregate for run list/detail responses."""

    total: int = 0
    last_event_type: str | None = None
    last_event_at: datetime | None = None


class AgentRunResponse(BaseModel):
    """Schema for agent run response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID | None
    agent_profile_id: UUID | None = None
    workflow_version_id: UUID | None
    run_type: str = "workflow"
    input_data: dict[str, Any] = Field(default_factory=dict)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime
    agent_profile: AgentRunAgentProfileSummary | None = None
    workflow: AgentRunWorkflowSummary | None = None
    task_summary: AgentRunTaskSummary = Field(default_factory=AgentRunTaskSummary)
    event_summary: AgentRunEventSummary = Field(default_factory=AgentRunEventSummary)
    duration_ms: float | None = None
    progress_percent: int = 0
    can_retry: bool = False
    can_cancel: bool = False
    gate_summary: dict[str, Any] = Field(default_factory=dict)
    can_resume: bool = False
    requires_human_action: bool = False
    status_hint: str | None = None


class AgentRunControlActionRequest(BaseModel):
    """Request to resolve or route a workflow control node."""

    action: str = Field(..., description="approve, reject, resume, or skip")
    node_id: str | None = Field(None, description="Control node ID to resolve")
    comment: str | None = Field(None, description="Human operator comment")
    output_data: dict[str, Any] = Field(default_factory=dict)


class AgentRunListResponse(PaginatedResponse[AgentRunResponse]):
    """Schema for paginated agent run list response."""

    pass


class OrchestrationKpis(BaseModel):
    """High-level production readiness KPIs for intelligent orchestration."""

    active_agents: int = 0
    published_skills: int = 0
    active_workflows: int = 0
    executable_workflows: int = 0
    total_runs: int = 0
    running_runs: int = 0
    failed_runs: int = 0
    recoverable_runs: int = 0


class OrchestrationHealthIssue(BaseModel):
    """Actionable health issue or recommendation."""

    severity: str
    code: str
    title: str
    detail: str
    action_label: str | None = None
    action_href: str | None = None


class OrchestrationDashboardResponse(BaseModel):
    """Full intelligent orchestration cockpit data."""

    generated_at: datetime
    readiness_score: int
    kpis: OrchestrationKpis
    run_status_counts: dict[str, int] = Field(default_factory=dict)
    workflow_category_counts: dict[str, int] = Field(default_factory=dict)
    recent_runs: list[AgentRunResponse] = Field(default_factory=list)
    recommendations: list[OrchestrationHealthIssue] = Field(default_factory=list)
    template_count: int = 0


class OrchestrationBootstrapResponse(BaseModel):
    """Explicit first-run initialization result for intelligent orchestration."""

    message: str
    initialized: dict[str, int] = Field(default_factory=dict)
    dashboard: OrchestrationDashboardResponse


# AgentTask Schemas
class AgentTaskResponse(BaseModel):
    """Schema for agent task response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_run_id: UUID
    tenant_id: UUID | None
    node_id: str
    skill_name: str | None
    tool_name: str | None
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    status: str
    retries: int
    max_retries: int
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class AgentTaskListResponse(PaginatedResponse[AgentTaskResponse]):
    """Schema for paginated agent task list response."""

    pass


# AgentEvent Schemas
class AgentEventResponse(BaseModel):
    """Schema for agent event response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_run_id: UUID
    tenant_id: UUID | None
    event_type: str
    event_data: dict[str, Any]
    created_at: datetime


class AgentEventListResponse(PaginatedResponse[AgentEventResponse]):
    """Paginated agent event response."""

    pass


class AgentRunActionResponse(BaseModel):
    """Response for run control actions."""

    run_id: UUID
    status: str
    message: str


class DAGValidationIssue(BaseModel):
    """Single workflow DAG validation issue."""

    severity: str = Field(..., description="error or warning")
    code: str = Field(default="workflow_dag_issue")
    node_id: str | None = None
    message: str


class WorkflowDAGValidateRequest(BaseModel):
    """Request for validating a workflow DAG."""

    dag_json: dict[str, Any] = Field(default_factory=dict)


class DAGValidationResponse(BaseModel):
    """Workflow DAG validation result."""

    valid: bool
    issues: list[DAGValidationIssue] = Field(default_factory=list)
    execution_order: list[str] = Field(default_factory=list)


class WorkflowDAGPreviewRequest(BaseModel):
    """Request for workflow execution preview and preflight inspection."""

    dag_json: dict[str, Any] = Field(default_factory=dict)
    input_data: dict[str, Any] = Field(default_factory=dict)


class WorkflowDAGPreviewResponse(BaseModel):
    """Workflow execution preview for visual runtime planning."""

    valid: bool
    issues: list[DAGValidationIssue] = Field(default_factory=list)
    execution_order: list[str] = Field(default_factory=list)
    parallel_groups: list[dict[str, Any]] = Field(default_factory=list)
    approval_gates: list[dict[str, Any]] = Field(default_factory=list)
    condition_paths: list[dict[str, Any]] = Field(default_factory=list)
    estimated_steps: int = 0
    blocking_issues: list[DAGValidationIssue] = Field(default_factory=list)


class WorkflowProductionPreflightGate(BaseModel):
    """Release-style gate for running a workflow in production context."""

    status: str
    label: str
    summary: str
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WorkflowProductionPreflightCheck(BaseModel):
    """Single actionable workflow preflight check."""

    code: str
    severity: str
    title: str
    detail: str
    status: str
    action_label: str | None = None
    action_href: str | None = None


class WorkflowProductionPreflightResponse(BaseModel):
    """Production preflight for a concrete workflow and project context."""

    workflow_id: UUID
    workflow_name: str
    project_id: UUID | None = None
    active_version_id: UUID | None = None
    release_gate: WorkflowProductionPreflightGate
    preview: WorkflowDAGPreviewResponse
    checks: list[WorkflowProductionPreflightCheck] = Field(default_factory=list)
    recent_runs: list[AgentRunResponse] = Field(default_factory=list)
    next_actions: list[WorkflowProductionPreflightCheck] = Field(default_factory=list)


# Skill Execution Schemas
class SkillExecuteRequest(BaseModel):
    """Schema for executing a skill."""

    skill_name: str = Field(..., description="Name of the skill to execute")
    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Input data for the skill",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution context",
    )


class SkillExecuteResponse(BaseModel):
    """Schema for skill execution response."""

    success: bool
    output_data: dict[str, Any] | None = None
    error_message: str | None = None
    execution_time_ms: float | None = None


class SkillCatalogTestRequest(BaseModel):
    """Request for testing a catalog skill."""

    project_id: UUID | None = None
    input_data: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class SkillCatalogTestResponse(BaseModel):
    """Catalog skill test result."""

    skill_id: UUID
    skill_name: str
    success: bool
    output_data: dict[str, Any] | None = None
    error_message: str | None = None
    execution_time_ms: float | None = None
    mode: str = Field(default="contract")
    run_id: UUID | None = None
    task_id: UUID | None = None


class SkillInfoResponse(BaseModel):
    """Schema for skill information."""

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    is_builtin: bool


class SkillListResponse(BaseModel):
    """Schema for list of available skills."""

    skills: list[SkillInfoResponse]


# Workflow Execution Request
class WorkflowExecuteRequest(BaseModel):
    """Schema for executing a workflow."""

    workflow_id: UUID = Field(..., description="Workflow definition ID")
    project_id: UUID = Field(..., description="Project ID to run workflow for")
    version_id: UUID | None = Field(
        None,
        description="Specific version to use (uses active if not provided)",
    )
    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Input data for the workflow",
    )


class WorkflowExecuteResponse(BaseModel):
    """Schema for workflow execution response."""

    run_id: UUID = Field(..., description="Agent run ID")
    status: str = Field(..., description="Initial run status")
    message: str = Field(..., description="Response message")


# Workflow Version Activation
class WorkflowVersionActivateRequest(BaseModel):
    """Schema for activating a workflow version."""

    pass  # No body required, version ID comes from path


class WorkflowVersionActivateResponse(BaseModel):
    """Schema for workflow version activation response."""

    version_id: UUID
    workflow_definition_id: UUID
    is_active: bool
    message: str
