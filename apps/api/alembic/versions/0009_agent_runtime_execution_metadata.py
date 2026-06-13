"""Add agent runtime execution metadata.

Persists run type, optional agent profile linkage, and execution metadata so
direct skill, agent-profile, and workflow runs can share one traceable run log.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0009_agent_runtime_meta"
down_revision = "0008_skill_gov_gen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add execution metadata columns to agent runs."""
    op.alter_column("agent_runs", "project_id", existing_type=UUID(as_uuid=True), nullable=True)
    op.add_column("agent_runs", sa.Column("agent_profile_id", UUID(as_uuid=True), nullable=True))
    op.add_column("agent_runs", sa.Column("run_type", sa.String(30), nullable=False, server_default="workflow"))
    op.add_column("agent_runs", sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_foreign_key(
        "fk_agent_runs_agent_profile_id",
        "agent_runs",
        "agent_profiles",
        ["agent_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_agent_runs_agent_profile_id", "agent_runs", ["agent_profile_id"], if_not_exists=True)
    op.create_index("ix_agent_runs_run_type", "agent_runs", ["run_type"], if_not_exists=True)


def downgrade() -> None:
    """Remove execution metadata columns from agent runs."""
    op.drop_index("ix_agent_runs_run_type", table_name="agent_runs", if_exists=True)
    op.drop_index("ix_agent_runs_agent_profile_id", table_name="agent_runs", if_exists=True)
    op.drop_constraint("fk_agent_runs_agent_profile_id", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "metadata")
    op.drop_column("agent_runs", "run_type")
    op.drop_column("agent_runs", "agent_profile_id")
    op.alter_column("agent_runs", "project_id", existing_type=UUID(as_uuid=True), nullable=False)
