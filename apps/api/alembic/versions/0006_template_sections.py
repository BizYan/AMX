"""Add structured template sections and section skill bindings."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0006_template_sections"
down_revision = "0005_traceability_impact"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create section-level template configuration tables."""
    op.create_table(
        "template_sections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("template_version_id", UUID(as_uuid=True), sa.ForeignKey("template_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_section_id", UUID(as_uuid=True), sa.ForeignKey("template_sections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("section_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_requirement", sa.Text(), nullable=False, server_default=""),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("required_inputs", JSONB, nullable=False, server_default="[]"),
        sa.Column("quality_rules", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )
    op.create_index("ix_template_sections_tenant_id", "template_sections", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_template_sections_version_id", "template_sections", ["template_version_id"], if_not_exists=True)
    op.create_index("ix_template_sections_parent_id", "template_sections", ["parent_section_id"], if_not_exists=True)
    op.create_index("ix_template_sections_section_key", "template_sections", ["template_version_id", "section_key"], if_not_exists=True)
    op.create_index("ix_template_sections_order", "template_sections", ["template_version_id", "position"], if_not_exists=True)

    op.create_table(
        "template_section_skill_bindings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("section_id", UUID(as_uuid=True), sa.ForeignKey("template_sections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", UUID(as_uuid=True), sa.ForeignKey("agent_skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_required", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("prompt_override", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        if_not_exists=True,
    )
    op.create_index("ix_template_section_skill_bindings_tenant_id", "template_section_skill_bindings", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_template_section_skill_bindings_section_id", "template_section_skill_bindings", ["section_id"], if_not_exists=True)
    op.create_index("ix_template_section_skill_bindings_skill_id", "template_section_skill_bindings", ["skill_id"], if_not_exists=True)
    op.create_index("ix_template_section_skill_bindings_order", "template_section_skill_bindings", ["section_id", "order_index"], if_not_exists=True)


def downgrade() -> None:
    """Drop section-level template configuration tables."""
    op.drop_index("ix_template_section_skill_bindings_order", table_name="template_section_skill_bindings", if_exists=True)
    op.drop_index("ix_template_section_skill_bindings_skill_id", table_name="template_section_skill_bindings", if_exists=True)
    op.drop_index("ix_template_section_skill_bindings_section_id", table_name="template_section_skill_bindings", if_exists=True)
    op.drop_index("ix_template_section_skill_bindings_tenant_id", table_name="template_section_skill_bindings", if_exists=True)
    op.drop_table("template_section_skill_bindings", if_exists=True)

    op.drop_index("ix_template_sections_order", table_name="template_sections", if_exists=True)
    op.drop_index("ix_template_sections_section_key", table_name="template_sections", if_exists=True)
    op.drop_index("ix_template_sections_parent_id", table_name="template_sections", if_exists=True)
    op.drop_index("ix_template_sections_version_id", table_name="template_sections", if_exists=True)
    op.drop_index("ix_template_sections_tenant_id", table_name="template_sections", if_exists=True)
    op.drop_table("template_sections", if_exists=True)
