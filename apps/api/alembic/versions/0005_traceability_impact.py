"""Add persistent document traceability and impact workflow tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0005_traceability_impact"
down_revision = "0004_agent_orchestration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create traceability reference, impact analysis, and sync proposal tables."""
    op.create_table(
        "document_references",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_document_version", sa.Integer(), nullable=False),
        sa.Column("target_document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_document_version", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(50), nullable=False, server_default="derives_from"),
        sa.Column("source_section", sa.String(255), nullable=True),
        sa.Column("target_section", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )
    op.create_index("ix_document_references_tenant_id", "document_references", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_document_references_project_id", "document_references", ["project_id"], if_not_exists=True)
    op.create_index("ix_document_references_source_document_id", "document_references", ["source_document_id"], if_not_exists=True)
    op.create_index("ix_document_references_target_document_id", "document_references", ["target_document_id"], if_not_exists=True)
    op.create_index("ix_document_references_status", "document_references", ["status"], if_not_exists=True)

    op.create_table(
        "document_impact_analyses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger_document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger_document_version", sa.Integer(), nullable=False),
        sa.Column("change_request_id", UUID(as_uuid=True), sa.ForeignKey("change_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("trigger_type", sa.String(50), nullable=False, server_default="content_changed"),
        sa.Column("impact_level", sa.String(20), nullable=False, server_default="low"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("analysis_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        if_not_exists=True,
    )
    op.create_index("ix_document_impact_analyses_tenant_id", "document_impact_analyses", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_document_impact_analyses_project_id", "document_impact_analyses", ["project_id"], if_not_exists=True)
    op.create_index("ix_document_impact_analyses_trigger_document_id", "document_impact_analyses", ["trigger_document_id"], if_not_exists=True)
    op.create_index("ix_document_impact_analyses_status", "document_impact_analyses", ["status"], if_not_exists=True)

    op.create_table(
        "document_sync_proposals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("impact_analysis_id", UUID(as_uuid=True), sa.ForeignKey("document_impact_analyses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reference_id", UUID(as_uuid=True), sa.ForeignKey("document_references.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_document_version", sa.Integer(), nullable=False),
        sa.Column("result_document_version", sa.Integer(), nullable=True),
        sa.Column("target_section", sa.String(255), nullable=True),
        sa.Column("impact_level", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("suggested_action", sa.String(50), nullable=False, server_default="sync_content"),
        sa.Column("candidate_content", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("decided_by", UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        if_not_exists=True,
    )
    op.create_index("ix_document_sync_proposals_tenant_id", "document_sync_proposals", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_document_sync_proposals_impact_analysis_id", "document_sync_proposals", ["impact_analysis_id"], if_not_exists=True)
    op.create_index("ix_document_sync_proposals_project_id", "document_sync_proposals", ["project_id"], if_not_exists=True)
    op.create_index("ix_document_sync_proposals_source_document_id", "document_sync_proposals", ["source_document_id"], if_not_exists=True)
    op.create_index("ix_document_sync_proposals_target_document_id", "document_sync_proposals", ["target_document_id"], if_not_exists=True)
    op.create_index("ix_document_sync_proposals_status", "document_sync_proposals", ["status"], if_not_exists=True)


def downgrade() -> None:
    """Drop persistent traceability workflow tables."""
    op.drop_index("ix_document_sync_proposals_status", table_name="document_sync_proposals", if_exists=True)
    op.drop_index("ix_document_sync_proposals_target_document_id", table_name="document_sync_proposals", if_exists=True)
    op.drop_index("ix_document_sync_proposals_source_document_id", table_name="document_sync_proposals", if_exists=True)
    op.drop_index("ix_document_sync_proposals_project_id", table_name="document_sync_proposals", if_exists=True)
    op.drop_index("ix_document_sync_proposals_impact_analysis_id", table_name="document_sync_proposals", if_exists=True)
    op.drop_index("ix_document_sync_proposals_tenant_id", table_name="document_sync_proposals", if_exists=True)
    op.drop_table("document_sync_proposals", if_exists=True)

    op.drop_index("ix_document_impact_analyses_status", table_name="document_impact_analyses", if_exists=True)
    op.drop_index("ix_document_impact_analyses_trigger_document_id", table_name="document_impact_analyses", if_exists=True)
    op.drop_index("ix_document_impact_analyses_project_id", table_name="document_impact_analyses", if_exists=True)
    op.drop_index("ix_document_impact_analyses_tenant_id", table_name="document_impact_analyses", if_exists=True)
    op.drop_table("document_impact_analyses", if_exists=True)

    op.drop_index("ix_document_references_status", table_name="document_references", if_exists=True)
    op.drop_index("ix_document_references_target_document_id", table_name="document_references", if_exists=True)
    op.drop_index("ix_document_references_source_document_id", table_name="document_references", if_exists=True)
    op.drop_index("ix_document_references_project_id", table_name="document_references", if_exists=True)
    op.drop_index("ix_document_references_tenant_id", table_name="document_references", if_exists=True)
    op.drop_table("document_references", if_exists=True)
