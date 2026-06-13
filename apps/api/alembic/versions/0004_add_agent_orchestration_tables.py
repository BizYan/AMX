"""Add agent orchestration tables.

Creates persistent skill catalog, agent profile, and agent skill binding tables
for the P4 Skill/Agent orchestration center.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0004_agent_orchestration"
down_revision = "0003_add_v020_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create agent orchestration tables."""
    op.create_table(
        "agent_skills",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("skill_type", sa.String(50), nullable=False, server_default="custom"),
        sa.Column("category", sa.String(100), nullable=False, server_default="custom"),
        sa.Column("input_schema_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("output_schema_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("supported_doc_types", JSONB, nullable=False, server_default="[]"),
        sa.Column("supported_industries", JSONB, nullable=False, server_default="[]"),
        sa.Column("version", sa.String(50), nullable=False, server_default="1.0.0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("is_builtin", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("implementation_ref", sa.String(255), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )
    op.create_index("ix_agent_skills_tenant_id", "agent_skills", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_agent_skills_name", "agent_skills", ["tenant_id", "name"], if_not_exists=True)
    op.create_index("ix_agent_skills_skill_type", "agent_skills", ["skill_type"], if_not_exists=True)
    op.create_index("ix_agent_skills_status", "agent_skills", ["status"], if_not_exists=True)
    op.create_index("ix_agent_skills_is_builtin", "agent_skills", ["is_builtin"], if_not_exists=True)

    op.create_table(
        "agent_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("agent_type", sa.String(50), nullable=False, server_default="custom"),
        sa.Column("applicable_doc_types", JSONB, nullable=False, server_default="[]"),
        sa.Column("default_template_id", UUID(as_uuid=True), nullable=True),
        sa.Column("tool_names", JSONB, nullable=False, server_default="[]"),
        sa.Column("workflow_definition_id", UUID(as_uuid=True), nullable=True),
        sa.Column("human_review_required", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )
    op.create_index("ix_agent_profiles_tenant_id", "agent_profiles", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_agent_profiles_agent_type", "agent_profiles", ["agent_type"], if_not_exists=True)
    op.create_index("ix_agent_profiles_status", "agent_profiles", ["status"], if_not_exists=True)
    op.create_index("ix_agent_profiles_created_by", "agent_profiles", ["created_by"], if_not_exists=True)
    op.create_index("ix_agent_profiles_workflow_definition_id", "agent_profiles", ["workflow_definition_id"], if_not_exists=True)

    op.create_table(
        "agent_skill_bindings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("agent_profile_id", UUID(as_uuid=True), sa.ForeignKey("agent_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", UUID(as_uuid=True), sa.ForeignKey("agent_skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_required", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        if_not_exists=True,
    )
    op.create_index("ix_agent_skill_bindings_agent_profile_id", "agent_skill_bindings", ["agent_profile_id"], if_not_exists=True)
    op.create_index("ix_agent_skill_bindings_skill_id", "agent_skill_bindings", ["skill_id"], if_not_exists=True)
    op.create_index("ix_agent_skill_bindings_order", "agent_skill_bindings", ["agent_profile_id", "order_index"], if_not_exists=True)
    op.create_index("ix_agent_skill_bindings_tenant_id", "agent_skill_bindings", ["tenant_id"], if_not_exists=True)


def downgrade() -> None:
    """Drop agent orchestration tables."""
    op.drop_table("agent_skill_bindings")
    op.drop_table("agent_profiles")
    op.drop_table("agent_skills")
