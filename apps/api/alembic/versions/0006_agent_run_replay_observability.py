"""Add replayable agent run input data."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0006_agent_run_replay"
down_revision = "0005_traceability_impact"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Persist workflow input data on agent runs for replay and audit."""
    op.add_column(
        "agent_runs",
        sa.Column(
            "input_data",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Remove persisted workflow input data from agent runs."""
    op.drop_column("agent_runs", "input_data")
