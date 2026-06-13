"""Add skill governance and document generation sessions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0008_skill_gov_gen"
down_revision = "0007_merge_0006_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add governance fields and interactive document generation tables."""
    op.add_column("agent_skills", sa.Column("display_name", sa.String(255), nullable=True))
    op.add_column("agent_skills", sa.Column("governance_scope", sa.String(30), nullable=False, server_default="tenant"))
    op.add_column("agent_skills", sa.Column("visibility", sa.String(30), nullable=False, server_default="tenant"))
    op.add_column("agent_skills", sa.Column("managed_by", sa.String(30), nullable=False, server_default="tenant"))
    op.add_column("agent_skills", sa.Column("is_locked", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_agent_skills_governance_scope", "agent_skills", ["governance_scope"], if_not_exists=True)

    op.create_table(
        "document_generation_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("template_id", UUID(as_uuid=True), nullable=True),
        sa.Column("doc_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("generation_mode", sa.String(30), nullable=False, server_default="interactive"),
        sa.Column("current_section_key", sa.String(120), nullable=True),
        sa.Column("context_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("stash_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("quality_summary_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        if_not_exists=True,
    )
    op.create_index("ix_document_generation_sessions_tenant_id", "document_generation_sessions", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_document_generation_sessions_project_id", "document_generation_sessions", ["project_id"], if_not_exists=True)
    op.create_index("ix_document_generation_sessions_doc_type", "document_generation_sessions", ["doc_type"], if_not_exists=True)
    op.create_index("ix_document_generation_sessions_status", "document_generation_sessions", ["status"], if_not_exists=True)
    op.create_index("ix_document_generation_sessions_document_id", "document_generation_sessions", ["document_id"], if_not_exists=True)
    op.create_index("ix_document_generation_sessions_template_id", "document_generation_sessions", ["template_id"], if_not_exists=True)
    op.create_index("ix_document_generation_sessions_created_by", "document_generation_sessions", ["created_by"], if_not_exists=True)

    op.create_table(
        "document_generation_sections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("document_generation_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_requirement", sa.Text(), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("pending_questions_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("confirmed_facts_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("quality_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("required_inputs", JSONB, nullable=False, server_default="[]"),
        sa.Column("quality_rules", JSONB, nullable=False, server_default="[]"),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        if_not_exists=True,
    )
    op.create_index("ix_document_generation_sections_tenant_id", "document_generation_sections", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_document_generation_sections_session_id", "document_generation_sections", ["session_id"], if_not_exists=True)
    op.create_index("ix_document_generation_sections_key", "document_generation_sections", ["session_id", "section_key"], if_not_exists=True)
    op.create_index("ix_document_generation_sections_order", "document_generation_sections", ["session_id", "position"], if_not_exists=True)

    op.create_table(
        "document_generation_steps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("document_generation_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("action_type", sa.String(30), nullable=False),
        sa.Column("section_key", sa.String(120), nullable=True),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("patch_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("quality_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        if_not_exists=True,
    )
    op.create_index("ix_document_generation_steps_tenant_id", "document_generation_steps", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_document_generation_steps_session_id", "document_generation_steps", ["session_id"], if_not_exists=True)
    op.create_index("ix_document_generation_steps_order", "document_generation_steps", ["session_id", "step_index"], if_not_exists=True)
    op.create_index("ix_document_generation_steps_created_by", "document_generation_steps", ["created_by"], if_not_exists=True)


def downgrade() -> None:
    """Remove interactive document generation tables and governance fields."""
    op.drop_index("ix_document_generation_steps_created_by", table_name="document_generation_steps", if_exists=True)
    op.drop_index("ix_document_generation_steps_order", table_name="document_generation_steps", if_exists=True)
    op.drop_index("ix_document_generation_steps_session_id", table_name="document_generation_steps", if_exists=True)
    op.drop_index("ix_document_generation_steps_tenant_id", table_name="document_generation_steps", if_exists=True)
    op.drop_table("document_generation_steps", if_exists=True)

    op.drop_index("ix_document_generation_sections_order", table_name="document_generation_sections", if_exists=True)
    op.drop_index("ix_document_generation_sections_key", table_name="document_generation_sections", if_exists=True)
    op.drop_index("ix_document_generation_sections_session_id", table_name="document_generation_sections", if_exists=True)
    op.drop_index("ix_document_generation_sections_tenant_id", table_name="document_generation_sections", if_exists=True)
    op.drop_table("document_generation_sections", if_exists=True)

    op.drop_index("ix_document_generation_sessions_created_by", table_name="document_generation_sessions", if_exists=True)
    op.drop_index("ix_document_generation_sessions_template_id", table_name="document_generation_sessions", if_exists=True)
    op.drop_index("ix_document_generation_sessions_document_id", table_name="document_generation_sessions", if_exists=True)
    op.drop_index("ix_document_generation_sessions_status", table_name="document_generation_sessions", if_exists=True)
    op.drop_index("ix_document_generation_sessions_doc_type", table_name="document_generation_sessions", if_exists=True)
    op.drop_index("ix_document_generation_sessions_project_id", table_name="document_generation_sessions", if_exists=True)
    op.drop_index("ix_document_generation_sessions_tenant_id", table_name="document_generation_sessions", if_exists=True)
    op.drop_table("document_generation_sessions", if_exists=True)

    op.drop_index("ix_agent_skills_governance_scope", table_name="agent_skills", if_exists=True)
    op.drop_column("agent_skills", "is_locked")
    op.drop_column("agent_skills", "managed_by")
    op.drop_column("agent_skills", "visibility")
    op.drop_column("agent_skills", "governance_scope")
    op.drop_column("agent_skills", "display_name")
