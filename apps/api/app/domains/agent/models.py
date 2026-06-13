"""Agent Runtime Domain Models

Database models for workflow definitions, agent runs, tasks, and events.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UuidMixin,
)

if TYPE_CHECKING:
    pass


class WorkflowCategory(str, Enum):
    """Workflow category enumeration."""

    DOCUMENT_GENERATION = "document_generation"
    REQUIREMENT_ANALYSIS = "requirement_analysis"
    QUALITY_ASSESSMENT = "quality_assessment"
    EXPORT_ORCHESTRATION = "export_orchestration"
    CUSTOM = "custom"


class SkillStatus(str, Enum):
    """Skill publication status."""

    DRAFT = "draft"
    PUBLISHED = "published"
    DISABLED = "disabled"


class AgentProfileStatus(str, Enum):
    """Agent profile lifecycle status."""

    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"


class AgentRunStatus(str, Enum):
    """Agent run status enumeration."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentTaskStatus(str, Enum):
    """Agent task status enumeration."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentSkill(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Tenant-visible skill catalog entry.

    Built-in skills are seeded into the same catalog as tenant custom skills so
    agent profiles and workflow nodes can bind to one stable data model.
    """

    __tablename__ = "agent_skills"

    name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    skill_type = Column(String(50), nullable=False, default="custom")
    category = Column(String(100), nullable=False, default="custom")
    input_schema_json = Column(JSONB, nullable=False, default=dict)
    output_schema_json = Column(JSONB, nullable=False, default=dict)
    supported_doc_types = Column(JSONB, nullable=False, default=list)
    supported_industries = Column(JSONB, nullable=False, default=list)
    version = Column(String(50), nullable=False, default="1.0.0")
    status = Column(String(20), nullable=False, default=SkillStatus.DRAFT.value)
    is_builtin = Column(Integer, nullable=False, default=0)
    governance_scope = Column(String(30), nullable=False, default="tenant")
    visibility = Column(String(30), nullable=False, default="tenant")
    managed_by = Column(String(30), nullable=False, default="tenant")
    is_locked = Column(Integer, nullable=False, default=0)
    implementation_ref = Column(String(255), nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=False, default=dict)
    created_by = Column(UUID(as_uuid=True), nullable=False, index=True)

    @property
    def effective_display_name(self) -> str:
        """Human-facing name with machine-key fallback."""
        return self.display_name or self.name

    @property
    def can_edit(self) -> bool:
        """Whether the current tenant catalog entry is user-editable."""
        return not bool(self.is_locked) and self.governance_scope not in {"system", "platform"}

    @property
    def can_publish(self) -> bool:
        """Whether the current tenant catalog entry can be published by tenant users."""
        return self.can_edit

    @property
    def can_disable(self) -> bool:
        """Whether the current tenant catalog entry can be disabled by tenant users."""
        return self.can_edit

    @property
    def locked_reason(self) -> str | None:
        """User-facing explanation for locked system/platform skills."""
        if self.can_edit:
            return None
        if self.governance_scope == "system":
            return "系统级 Skill 由平台维护，当前租户不可修改。"
        if self.governance_scope == "platform":
            return "平台级 Skill 可绑定和测试，但不可由顾问直接修改。"
        if self.is_locked:
            return "该 Skill 已锁定，当前用户不可修改。"
        return None

    bindings = relationship(
        "AgentSkillBinding",
        back_populates="skill",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_agent_skills_tenant_id", "tenant_id"),
        Index("ix_agent_skills_name", "tenant_id", "name"),
        Index("ix_agent_skills_skill_type", "skill_type"),
        Index("ix_agent_skills_status", "status"),
        Index("ix_agent_skills_is_builtin", "is_builtin"),
    )


class AgentProfile(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Configurable agent profile assembled from skills, tools, and workflow."""

    __tablename__ = "agent_profiles"

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    agent_type = Column(String(50), nullable=False, default="custom")
    applicable_doc_types = Column(JSONB, nullable=False, default=list)
    default_template_id = Column(UUID(as_uuid=True), nullable=True)
    tool_names = Column(JSONB, nullable=False, default=list)
    workflow_definition_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_definitions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    human_review_required = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default=AgentProfileStatus.ACTIVE.value)
    system_prompt = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=False, index=True)

    workflow_definition = relationship("WorkflowDefinition", lazy="selectin")
    skill_bindings = relationship(
        "AgentSkillBinding",
        back_populates="agent_profile",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="AgentSkillBinding.order_index",
    )

    __table_args__ = (
        Index("ix_agent_profiles_tenant_id", "tenant_id"),
        Index("ix_agent_profiles_agent_type", "agent_type"),
        Index("ix_agent_profiles_status", "status"),
        Index("ix_agent_profiles_created_by", "created_by"),
    )


class AgentSkillBinding(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Ordered skill binding for an agent profile."""

    __tablename__ = "agent_skill_bindings"

    agent_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_index = Column(Integer, nullable=False, default=0)
    is_required = Column(Integer, nullable=False, default=1)

    agent_profile = relationship("AgentProfile", back_populates="skill_bindings")
    skill = relationship("AgentSkill", back_populates="bindings", lazy="selectin")

    __table_args__ = (
        Index("ix_agent_skill_bindings_agent_profile_id", "agent_profile_id"),
        Index("ix_agent_skill_bindings_skill_id", "skill_id"),
        Index("ix_agent_skill_bindings_order", "agent_profile_id", "order_index"),
    )


class WorkflowDefinition(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Workflow definition model.

    Represents a reusable workflow template that can have multiple versions.
    Each version contains a DAG defining the execution flow.
    """

    __tablename__ = "workflow_definitions"

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(
        String(50),
        nullable=False,
        default=WorkflowCategory.CUSTOM.value,
    )
    version_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Integer, nullable=False, default=1)
    created_by = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # Relations
    versions = relationship(
        "WorkflowVersion",
        back_populates="workflow_definition",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_workflow_definitions_tenant_id", "tenant_id"),
        Index("ix_workflow_definitions_category", "category"),
        Index("ix_workflow_definitions_created_by", "created_by"),
    )


class WorkflowVersion(Base, UuidMixin, TimestampMixin):
    """Workflow version model.

    Stores a specific version of a workflow definition with its DAG
    and skill/tool contracts.
    """

    __tablename__ = "workflow_versions"

    workflow_definition_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)
    dag_json = Column(JSONB, nullable=False, default=dict)
    skill_contracts_json = Column(JSONB, nullable=False, default=list)
    tool_contracts_json = Column(JSONB, nullable=False, default=list)
    is_active = Column(Integer, nullable=False, default=0)
    created_by = Column(
        UUID(as_uuid=True),
        nullable=False,
    )

    # Relations
    workflow_definition = relationship(
        "WorkflowDefinition",
        back_populates="versions",
    )
    agent_runs = relationship(
        "AgentRun",
        back_populates="workflow_version",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_workflow_versions_workflow_definition_id", "workflow_definition_id"),
        Index("ix_workflow_versions_version", "workflow_definition_id", "version"),
        Index("ix_workflow_versions_is_active", "is_active"),
    )


class AgentRun(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Agent run model.

    Represents a single execution of a workflow, tracking overall
    status and timing.
    """

    __tablename__ = "agent_runs"

    project_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    agent_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workflow_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    run_type = Column(String(30), nullable=False, default="workflow")
    input_data = Column(JSONB, nullable=False, default=dict)
    metadata_json = Column("metadata", JSONB, nullable=False, default=dict)
    status = Column(
        String(20),
        nullable=False,
        default=AgentRunStatus.PENDING.value,
        index=True,
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    # Relations
    workflow_version = relationship(
        "WorkflowVersion",
        back_populates="agent_runs",
    )
    agent_profile = relationship("AgentProfile", lazy="selectin")
    tasks = relationship(
        "AgentTask",
        back_populates="agent_run",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    events = relationship(
        "AgentEvent",
        back_populates="agent_run",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    @property
    def workflow(self) -> dict | None:
        """Compact workflow identity for run list/detail responses."""
        if self.workflow_version is None:
            return None
        workflow_definition = self.workflow_version.workflow_definition
        return {
            "version_id": self.workflow_version.id,
            "workflow_definition_id": self.workflow_version.workflow_definition_id,
            "workflow_name": workflow_definition.name if workflow_definition else None,
            "category": workflow_definition.category if workflow_definition else None,
            "version": self.workflow_version.version,
            "is_active": bool(self.workflow_version.is_active),
        }

    @property
    def task_summary(self) -> dict:
        """Aggregate task counts for UI progress and diagnostics."""
        tasks = list(self.tasks or [])
        counts = {
            AgentTaskStatus.PENDING.value: 0,
            AgentTaskStatus.RUNNING.value: 0,
            AgentTaskStatus.COMPLETED.value: 0,
            AgentTaskStatus.FAILED.value: 0,
        }
        for task in tasks:
            if task.status in counts:
                counts[task.status] += 1
        last_task = tasks[-1] if tasks else None
        return {
            "total": len(tasks),
            "pending": counts[AgentTaskStatus.PENDING.value],
            "running": counts[AgentTaskStatus.RUNNING.value],
            "completed": counts[AgentTaskStatus.COMPLETED.value],
            "failed": counts[AgentTaskStatus.FAILED.value],
            "last_task_id": last_task.id if last_task else None,
            "last_task_status": last_task.status if last_task else None,
            "last_error_message": next(
                (task.error_message for task in reversed(tasks) if task.error_message),
                self.error_message,
            ),
        }

    @property
    def event_summary(self) -> dict:
        """Aggregate event counts and latest event for list/detail responses."""
        events = list(self.events or [])
        last_event = events[-1] if events else None
        return {
            "total": len(events),
            "last_event_type": last_event.event_type if last_event else None,
            "last_event_at": last_event.created_at if last_event else None,
        }

    @property
    def duration_ms(self) -> float | None:
        """Run duration in milliseconds when enough timing data exists."""
        start_time = self.started_at or (self.created_at if self.completed_at else None)
        if start_time is None:
            return None
        end_time = self.completed_at or datetime.now(timezone.utc)
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        return round((end_time - start_time).total_seconds() * 1000, 2)

    @property
    def progress_percent(self) -> int:
        """Task-based progress percentage with stable terminal fallbacks."""
        tasks = list(self.tasks or [])
        if tasks:
            completed = len(
                [task for task in tasks if task.status == AgentTaskStatus.COMPLETED.value]
            )
            return round((completed / len(tasks)) * 100)
        if self.status == AgentRunStatus.COMPLETED.value:
            return 100
        return 0

    @property
    def can_retry(self) -> bool:
        """Whether retry is currently allowed."""
        return self.status in {AgentRunStatus.FAILED.value, AgentRunStatus.CANCELLED.value}

    @property
    def can_cancel(self) -> bool:
        """Whether cancellation is currently allowed."""
        return self.status in {AgentRunStatus.PENDING.value, AgentRunStatus.RUNNING.value}

    @property
    def gate_summary(self) -> dict:
        """Runtime gate hints derived from execution metadata."""
        metadata = self.metadata_json or {}
        approval_gates = metadata.get("approval_gates") or []
        condition_paths = metadata.get("condition_paths") or []
        parallel_groups = metadata.get("parallel_groups") or []
        return {
            "approval_gates": len(approval_gates) if isinstance(approval_gates, list) else 0,
            "condition_paths": len(condition_paths) if isinstance(condition_paths, list) else 0,
            "parallel_groups": len(parallel_groups) if isinstance(parallel_groups, list) else 0,
            "requires_human_action": bool(metadata.get("requires_human_action")),
            "status_hint": metadata.get("status_hint"),
        }

    @property
    def can_resume(self) -> bool:
        """Whether the run can be resumed from a recoverable control state."""
        metadata = self.metadata_json or {}
        return bool(metadata.get("can_resume")) or self.status in {
            AgentRunStatus.FAILED.value,
            AgentRunStatus.CANCELLED.value,
        }

    @property
    def requires_human_action(self) -> bool:
        """Whether the run details should surface a human handling prompt."""
        return bool((self.metadata_json or {}).get("requires_human_action"))

    @property
    def status_hint(self) -> str | None:
        """Stable UI hint for run detail status banners."""
        return (self.metadata_json or {}).get("status_hint")

    __table_args__ = (
        Index("ix_agent_runs_tenant_id", "tenant_id"),
        Index("ix_agent_runs_project_id", "project_id"),
        Index("ix_agent_runs_agent_profile_id", "agent_profile_id"),
        Index("ix_agent_runs_run_type", "run_type"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_workflow_version_id", "workflow_version_id"),
    )


class AgentTask(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Agent task model.

    Represents a single task within an agent run, typically mapping
    to a node in the workflow DAG.
    """

    __tablename__ = "agent_tasks"

    agent_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id = Column(String(255), nullable=False)
    skill_name = Column(String(255), nullable=True)
    tool_name = Column(String(255), nullable=True)
    input_data = Column(JSONB, nullable=False, default=dict)
    output_data = Column(JSONB, nullable=True)
    status = Column(
        String(20),
        nullable=False,
        default=AgentTaskStatus.PENDING.value,
        index=True,
    )
    retries = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relations
    agent_run = relationship(
        "AgentRun",
        back_populates="tasks",
    )

    __table_args__ = (
        Index("ix_agent_tasks_tenant_id", "tenant_id"),
        Index("ix_agent_tasks_agent_run_id", "agent_run_id"),
        Index("ix_agent_tasks_node_id", "node_id"),
        Index("ix_agent_tasks_status", "status"),
    )


class AgentEvent(Base, UuidMixin, TimestampMixin):
    """Agent event model.

    Stores events and logs from agent run execution for debugging
    and audit purposes.
    """

    __tablename__ = "agent_events"

    agent_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    event_type = Column(String(50), nullable=False)
    event_data = Column(JSONB, nullable=False, default=dict)

    # Relations
    agent_run = relationship(
        "AgentRun",
        back_populates="events",
    )

    __table_args__ = (
        Index("ix_agent_events_agent_run_id", "agent_run_id"),
        Index("ix_agent_events_tenant_id", "tenant_id"),
        Index("ix_agent_events_event_type", "event_type"),
    )
