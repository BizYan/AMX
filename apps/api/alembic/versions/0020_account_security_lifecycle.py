"""add account security lifecycle

Revision ID: 0020_account_security
Revises: 0019_source_ingestion_jobs
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_account_security"
down_revision = "0019_source_ingestion_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("security_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("users", "security_version", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "security_version")
