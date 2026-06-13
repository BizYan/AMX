"""Add v0.2.0 Tables

Creates tables for project invitations, project settings, source files, export jobs, export artifacts, templates, and template versions.
Also adds status column to projects.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision = "0003_add_v020_tables"
down_revision = "0002_partition_strategy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create new v0.2.0 tables and add status column to projects."""
    # 1. Add status column to projects
    op.add_column(
        "projects",
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        if_not_exists=True,
    )

    # 2. Create project_settings table
    op.create_table(
        "project_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("settings_json", JSONB, nullable=False, server_default="{}"),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )
    op.create_index("ix_project_settings_project_id", "project_settings", ["project_id"], unique=False, if_not_exists=True)
    op.create_index("ix_project_settings_tenant_id", "project_settings", ["tenant_id"], unique=False, if_not_exists=True)

    # 3. Create project_invitations table
    op.create_table(
        "project_invitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )
    op.create_index("ix_project_invitations_project_id", "project_invitations", ["project_id"], unique=False, if_not_exists=True)
    op.create_index("ix_project_invitations_email", "project_invitations", ["email"], unique=False, if_not_exists=True)
    op.create_index("ix_project_invitations_token", "project_invitations", ["token"], unique=True, if_not_exists=True)
    op.create_index("ix_project_invitations_expires_at", "project_invitations", ["expires_at"], unique=False, if_not_exists=True)
    op.create_index("ix_project_invitations_tenant_id", "project_invitations", ["tenant_id"], unique=False, if_not_exists=True)
    op.create_index("ix_project_invitations_project_email", "project_invitations", ["project_id", "email"], unique=False, if_not_exists=True)

    # 4. Create source_files table
    op.create_table(
        "source_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size", sa.String(50), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("metadata_json", JSONB, nullable=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )
    op.create_index("ix_source_files_project_id", "source_files", ["project_id"], unique=False, if_not_exists=True)
    op.create_index("ix_source_files_tenant_id", "source_files", ["tenant_id"], unique=False, if_not_exists=True)
    op.create_index("ix_source_files_status", "source_files", ["status"], unique=False, if_not_exists=True)
    op.create_index("ix_source_files_hash", "source_files", ["hash"], unique=False, if_not_exists=True)

    # 5. Create export_jobs table
    op.create_table(
        "export_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=True),
        sa.Column("template_id", UUID(as_uuid=True), nullable=True),
        sa.Column("export_type", sa.String(20), nullable=False, server_default="word"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("output_path", sa.Text, nullable=True),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        if_not_exists=True,
    )
    op.create_index("ix_export_jobs_project_id", "export_jobs", ["project_id"], unique=False, if_not_exists=True)
    op.create_index("ix_export_jobs_document_id", "export_jobs", ["document_id"], unique=False, if_not_exists=True)
    op.create_index("ix_export_jobs_status", "export_jobs", ["status"], unique=False, if_not_exists=True)
    op.create_index("ix_export_jobs_created_by", "export_jobs", ["created_by"], unique=False, if_not_exists=True)
    op.create_index("ix_export_jobs_tenant_id", "export_jobs", ["tenant_id"], unique=False, if_not_exists=True)

    # 6. Create export_artifacts table
    op.create_table(
        "export_artifacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("export_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        if_not_exists=True,
    )
    op.create_index("ix_export_artifacts_job_id", "export_artifacts", ["job_id"], unique=False, if_not_exists=True)
    op.create_index("ix_export_artifacts_tenant_id", "export_artifacts", ["tenant_id"], unique=False, if_not_exists=True)

    # 7. Create templates table
    op.create_table(
        "templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("doc_type", sa.String(50), nullable=False, server_default="urs"),
        sa.Column("version_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.String(10), nullable=False, server_default="true"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )
    op.create_index("ix_templates_tenant_id", "templates", ["tenant_id"], unique=False, if_not_exists=True)
    op.create_index("ix_templates_doc_type", "templates", ["doc_type"], unique=False, if_not_exists=True)
    op.create_index("ix_templates_created_by", "templates", ["created_by"], unique=False, if_not_exists=True)
    op.create_index("ix_templates_deleted_at", "templates", ["deleted_at"], unique=False, if_not_exists=True)

    # 8. Create template_versions table
    op.create_table(
        "template_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary, nullable=True),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("placeholder_schema", JSONB, nullable=True),
        sa.Column("page_types", JSONB, nullable=True),
        sa.Column("is_active", sa.String(10), nullable=False, server_default="true"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        if_not_exists=True,
    )
    op.create_index("ix_template_versions_template_id", "template_versions", ["template_id"], unique=False, if_not_exists=True)
    op.create_index("ix_template_versions_version", "template_versions", ["template_id", "version"], unique=False, if_not_exists=True)


def downgrade() -> None:
    """Drop the new v0.2.0 tables and status column."""
    op.drop_table("template_versions")
    op.drop_table("templates")
    op.drop_table("export_artifacts")
    op.drop_table("export_jobs")
    op.drop_table("source_files")
    op.drop_table("project_invitations")
    op.drop_table("project_settings")

    op.drop_column("projects", "status")
