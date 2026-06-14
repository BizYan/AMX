"""add persistent source ingestion jobs

Revision ID: 0019_source_ingestion_jobs
Revises: 0018_project_invites
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_source_ingestion_jobs"
down_revision = "0018_project_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_ingestion_jobs",
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_ingestion_jobs_source_file_id", "source_ingestion_jobs", ["source_file_id"])
    op.create_index("ix_source_ingestion_jobs_project_id", "source_ingestion_jobs", ["project_id"])
    op.create_index("ix_source_ingestion_jobs_requested_by_id", "source_ingestion_jobs", ["requested_by_id"])
    op.create_index("ix_source_ingestion_jobs_status", "source_ingestion_jobs", ["status"])
    op.create_index("ix_source_ingestion_jobs_tenant_id", "source_ingestion_jobs", ["tenant_id"])
    op.create_index("ix_source_ingestion_jobs_tenant_status", "source_ingestion_jobs", ["tenant_id", "status"])
    op.create_index("ix_source_ingestion_jobs_source_status", "source_ingestion_jobs", ["source_file_id", "status"])


def downgrade() -> None:
    op.drop_table("source_ingestion_jobs")
