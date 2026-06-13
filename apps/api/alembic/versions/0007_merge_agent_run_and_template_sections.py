"""Merge agent run replay and template sections migration heads."""


revision = "0007_merge_0006_heads"
down_revision = ("0006_agent_run_replay", "0006_template_sections")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge parallel 0006 migration branches."""


def downgrade() -> None:
    """Split back to the parallel 0006 migration branches."""
