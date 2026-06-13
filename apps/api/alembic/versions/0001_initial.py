"""Initial Migration

Creates all core tables for the Consultant AI Workbench platform.
Includes multi-tenancy, authentication, and audit logging.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import Boolean

# revision identifiers
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create initial database schema."""
    # Enable required PostgreSQL extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")

    # Create tenants table
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    # Create users table
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"], unique=False)
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"], unique=False)

    # Create roles table
    op.create_table(
        "roles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("permissions", JSONB, nullable=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_roles_tenant_id", "roles", ["tenant_id"], unique=False)

    # Create user_roles join table
    op.create_table(
        "user_roles",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    )

    # Create projects table
    op.create_table(
        "projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("owner_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_projects_tenant_id", "projects", ["tenant_id"], unique=False)
    op.create_index("ix_projects_deleted_at", "projects", ["deleted_at"], unique=False)

    # Create project_members table
    op.create_table(
        "project_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="SET NULL"), nullable=True),
    )

    # Create jwt_blacklist table
    op.create_table(
        "jwt_blacklist",
        sa.Column("jti", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jwt_blacklist_expires_at", "jwt_blacklist", ["expires_at"], unique=False)

    # Create audit_logs table
    # NOTE: This table is designed for monthly partitioning in production
    # Partition by range on created_at using: PARTITION BY RANGE (created_at)
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=True),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"], unique=False)
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)

    # Create high-growth tables for agent runtime and observability
    # These tables are partition-ready for monthly partitioning in production

    # agent_events: stores agent execution events
    op.create_table(
        "agent_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("event_data", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_events_tenant_id", "agent_events", ["tenant_id"], unique=False)
    op.create_index("ix_agent_events_project_id", "agent_events", ["project_id"], unique=False)
    op.create_index("ix_agent_events_created_at", "agent_events", ["created_at"], unique=False)

    # metric_events: stores numeric metrics for monitoring
    op.create_table(
        "metric_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("metric_labels", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_metric_events_tenant_id", "metric_events", ["tenant_id"], unique=False)
    op.create_index("ix_metric_events_metric_name", "metric_events", ["metric_name"], unique=False)
    op.create_index("ix_metric_events_created_at", "metric_events", ["created_at"], unique=False)

    # provider_runs: stores LLM provider call metrics
    op.create_table(
        "provider_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_provider_runs_tenant_id", "provider_runs", ["tenant_id"], unique=False)
    op.create_index("ix_provider_runs_provider", "provider_runs", ["provider"], unique=False)
    op.create_index("ix_provider_runs_created_at", "provider_runs", ["created_at"], unique=False)

    # webhook_delivery_events: stores webhook delivery attempts
    op.create_table(
        "webhook_delivery_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column("webhook_id", UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("request_method", sa.String(10), nullable=True),
        sa.Column("request_url", sa.String(500), nullable=True),
        sa.Column("request_headers", JSONB, nullable=True),
        sa.Column("request_body", sa.Text, nullable=True),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("response_headers", JSONB, nullable=True),
        sa.Column("response_body", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_webhook_delivery_tenant_id", "webhook_delivery_events", ["tenant_id"], unique=False)
    op.create_index("ix_webhook_delivery_webhook_id", "webhook_delivery_events", ["webhook_id"], unique=False)
    op.create_index("ix_webhook_delivery_created_at", "webhook_delivery_events", ["created_at"], unique=False)

    # outbox_events: stores events for reliable outbox pattern
    op.create_table(
        "outbox_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column("aggregate_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_outbox_events_tenant_id", "outbox_events", ["tenant_id"], unique=False)
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"], unique=False)
    op.create_index("ix_outbox_events_scheduled_at", "outbox_events", ["scheduled_at"], unique=False)
    op.create_index("ix_outbox_events_created_at", "outbox_events", ["created_at"], unique=False)

    # llm_prompt_cache_entries: stores cached LLM prompts and responses
    op.create_table(
        "llm_prompt_cache_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column("cache_key", sa.String(500), nullable=False, unique=True),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("response", sa.Text, nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_llm_prompt_cache_tenant_id", "llm_prompt_cache_entries", ["tenant_id"], unique=False)
    op.create_index("ix_llm_prompt_cache_cache_key", "llm_prompt_cache_entries", ["cache_key"], unique=True)
    op.create_index("ix_llm_prompt_cache_prompt_hash", "llm_prompt_cache_entries", ["prompt_hash"], unique=False)
    op.create_index("ix_llm_prompt_cache_created_at", "llm_prompt_cache_entries", ["created_at"], unique=False)


def downgrade() -> None:
    """Drop all initial tables."""
    op.drop_table("llm_prompt_cache_entries")
    op.drop_table("outbox_events")
    op.drop_table("webhook_delivery_events")
    op.drop_table("provider_runs")
    op.drop_table("metric_events")
    op.drop_table("agent_events")
    op.drop_table("audit_logs")
    op.drop_table("jwt_blacklist")
    op.drop_table("project_members")
    op.drop_table("projects")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("users")
    op.drop_table("tenants")
