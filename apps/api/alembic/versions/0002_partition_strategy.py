"""DB Partition Strategy for High-Growth Tables

Adds partitioning support for high-growth tables:
- audit_logs, agent_events, metric_events, provider_runs, webhook_delivery_events,
  outbox_events, llm_prompt_cache_entries

Adds partition_type, retention_days, and archive_status columns.
Creates monthly partitions and partition management functions.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = "0002_partition_strategy"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

# High-growth tables requiring partitioning
HIGH_GROWTH_TABLES = [
    "audit_logs",
    "agent_events",
    "metric_events",
    "provider_runs",
    "outbox_events",
    "webhook_delivery_events",
    "llm_prompt_cache_entries",
]

# Tables with created_at for monthly partitioning
MONTHLY_PARTITION_TABLES = [
    "audit_logs",
    "agent_events",
    "metric_events",
    "provider_runs",
    "outbox_events",
]


def upgrade() -> None:
    """Add partition strategy columns and create monthly partitions."""

    # Add partition management columns to all high-growth tables
    for table_name in HIGH_GROWTH_TABLES:
        # Add partition_type column (monthly, weekly, none)
        op.execute(f"""
            ALTER TABLE {table_name}
            ADD COLUMN IF NOT EXISTS partition_type VARCHAR(20)
            DEFAULT 'monthly';
        """)

        # Add retention_days column
        op.execute(f"""
            ALTER TABLE {table_name}
            ADD COLUMN IF NOT EXISTS retention_days INTEGER
            DEFAULT 90;
        """)

        # Add archive_status column
        op.execute(f"""
            ALTER TABLE {table_name}
            ADD COLUMN IF NOT EXISTS archive_status VARCHAR(20)
            DEFAULT 'HOT';
        """)

        # Create index on archive_status
        op.execute(f"""
            CREATE INDEX IF NOT EXISTS ix_{table_name}_archive_status
            ON {table_name} (archive_status);
        """)

    # Create partition management metadata table
    op.create_table(
        "partition_metadata",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("table_name", sa.String(100), nullable=False, unique=True),
        sa.Column("partition_type", sa.String(20), nullable=False, default="monthly"),
        sa.Column("retention_days", sa.Integer(), nullable=False, default=90),
        sa.Column("archive_status", sa.String(20), nullable=False, default="HOT"),
        sa.Column("last_partition_created", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_partition_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_partition_metadata_table_name", "partition_metadata", ["table_name"], unique=True)

    # Insert metadata for each high-growth table
    for table_name in HIGH_GROWTH_TABLES:
        partition_type = "none" if table_name in ["webhook_delivery_events", "llm_prompt_cache_entries"] else "monthly"
        op.execute(f"""
            INSERT INTO partition_metadata (table_name, partition_type, retention_days, archive_status)
            VALUES ('{table_name}', '{partition_type}', 90, 'HOT')
            ON CONFLICT (table_name) DO NOTHING;
        """)

    # Create function to create monthly partitions
    op.execute("""
        CREATE OR REPLACE FUNCTION create_monthly_partition(
            target_table TEXT,
            partition_date DATE
        )
        RETURNS TEXT AS $$
        DECLARE
            partition_name TEXT;
            start_date DATE;
            end_date DATE;
            sql_text TEXT;
            parent_relkind CHAR;
        BEGIN
            -- Generate partition name like: audit_logs_2026_01
            partition_name := target_table || '_' || to_char(partition_date, 'YYYY_MM');

            -- Calculate partition date range (first of month to first of next month)
            start_date := date_trunc('month', partition_date);
            end_date := start_date + INTERVAL '1 month';

            SELECT relkind INTO parent_relkind
            FROM pg_class
            WHERE relname = target_table
            AND relnamespace = 'public'::regnamespace;

            IF parent_relkind IS DISTINCT FROM 'p' THEN
                RETURN 'Skipped partition creation for non-partitioned table: ' || target_table;
            END IF;

            -- Check if partition already exists
            IF NOT EXISTS (
                SELECT 1 FROM pg_tables
                WHERE schemaname = 'public'
                AND tablename = partition_name
            ) THEN
                -- Create the partition
                sql_text := 'CREATE TABLE ' || partition_name ||
                    ' PARTITION OF ' || target_table ||
                    ' FOR VALUES FROM (''' || start_date || ''') TO (''' || end_date || ''');';

                EXECUTE sql_text;

                -- Create indexes on the new partition
                IF target_table = 'audit_logs' THEN
                    EXECUTE 'CREATE INDEX ON ' || partition_name || ' (tenant_id, created_at);';
                    EXECUTE 'CREATE INDEX ON ' || partition_name || ' (created_at);';
                ELSIF target_table = 'agent_events' THEN
                    EXECUTE 'CREATE INDEX ON ' || partition_name || ' (tenant_id, created_at);';
                    EXECUTE 'CREATE INDEX ON ' || partition_name || ' (agent_run_id);';
                ELSIF target_table = 'metric_events' THEN
                    EXECUTE 'CREATE INDEX ON ' || partition_name || ' (tenant_id, recorded_at);';
                    EXECUTE 'CREATE INDEX ON ' || partition_name || ' (metric_name);';
                ELSIF target_table = 'provider_runs' THEN
                    EXECUTE 'CREATE INDEX ON ' || partition_name || ' (tenant_id, created_at);';
                    EXECUTE 'CREATE INDEX ON ' || partition_name || ' (provider_id);';
                ELSIF target_table = 'outbox_events' THEN
                    EXECUTE 'CREATE INDEX ON ' || partition_name || ' (tenant_id, created_at);';
                    EXECUTE 'CREATE INDEX ON ' || partition_name || ' (status);';
                END IF;

                RETURN 'Created partition: ' || partition_name;
            ELSE
                RETURN 'Partition already exists: ' || partition_name;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create function to create future partitions (for cron job)
    op.execute("""
        CREATE OR REPLACE FUNCTION create_future_partitions(
            target_table TEXT,
            months_ahead INTEGER DEFAULT 2
        )
        RETURNS TEXT AS $$
        DECLARE
            i INTEGER;
            result TEXT := '';
            partition_date DATE;
        BEGIN
            FOR i IN 0..months_ahead LOOP
                partition_date := (date_trunc('month', current_date) + (i || ' months')::INTERVAL)::DATE;
                result := result || create_monthly_partition(target_table, partition_date) || E'\\n';
            END LOOP;
            RETURN result;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create function to get partition info
    op.execute("""
        CREATE OR REPLACE FUNCTION get_partition_info(target_table TEXT)
        RETURNS TABLE (
            partition_name TEXT,
            partition_start DATE,
            partition_end DATE,
            row_count BIGINT
        ) AS $$
        BEGIN
            RETURN QUERY
            SELECT
                child.relname::TEXT AS partition_name,
                NULL::DATE AS partition_start,
                NULL::DATE AS partition_end,
                pg_stat_get_live_tuples(child.oid)::BIGINT AS row_count
            FROM pg_inherits
            JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
            JOIN pg_class child ON pg_inherits.inhrelid = child.oid
            WHERE parent.relname = target_table
            ORDER BY child.relname;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create partition maintenance function (cron-friendly)
    op.execute("""
        CREATE OR REPLACE FUNCTION maintain_partitions()
        RETURNS TEXT AS $$
        DECLARE
            result TEXT := '';
            row_data RECORD;
        BEGIN
            -- Create future partitions for all monthly partitioned tables
            FOR row_data IN SELECT table_name FROM partition_metadata WHERE partition_type = 'monthly' LOOP
                result := result || create_future_partitions(row_data.table_name, 2) || E'\\n';
            END LOOP;

            -- Update partition_metadata with last run timestamp
            UPDATE partition_metadata SET updated_at = NOW();

            RETURN result;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create cold archive trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION set_archive_status()
        RETURNS TEXT AS $$
        BEGIN
            -- Mark records older than retention period as COLD
            UPDATE audit_logs SET archive_status = 'COLD'
            WHERE archive_status = 'HOT'
            AND created_at < NOW() - INTERVAL '30 days'
            AND retention_days < (SELECT retention_days FROM partition_metadata WHERE table_name = 'audit_logs');

            UPDATE agent_events SET archive_status = 'COLD'
            WHERE archive_status = 'HOT'
            AND created_at < NOW() - INTERVAL '30 days'
            AND retention_days < (SELECT retention_days FROM partition_metadata WHERE table_name = 'agent_events');

            UPDATE metric_events SET archive_status = 'COLD'
            WHERE archive_status = 'HOT'
            AND recorded_at < NOW() - INTERVAL '30 days'
            AND retention_days < (SELECT retention_days FROM partition_metadata WHERE table_name = 'metric_events');

            UPDATE provider_runs SET archive_status = 'COLD'
            WHERE archive_status = 'HOT'
            AND created_at < NOW() - INTERVAL '30 days'
            AND retention_days < (SELECT retention_days FROM partition_metadata WHERE table_name = 'provider_runs');

            UPDATE outbox_events SET archive_status = 'COLD'
            WHERE archive_status = 'HOT'
            AND created_at < NOW() - INTERVAL '30 days'
            AND retention_days < (SELECT retention_days FROM partition_metadata WHERE table_name = 'outbox_events');

            UPDATE webhook_delivery_events SET archive_status = 'COLD'
            WHERE archive_status = 'HOT'
            AND created_at < NOW() - INTERVAL '30 days'
            AND retention_days < (SELECT retention_days FROM partition_metadata WHERE table_name = 'webhook_delivery_events');

            UPDATE llm_prompt_cache_entries SET archive_status = 'COLD'
            WHERE archive_status = 'HOT'
            AND created_at < NOW() - INTERVAL '30 days'
            AND retention_days < (SELECT retention_days FROM partition_metadata WHERE table_name = 'llm_prompt_cache_entries');

            RETURN 'Archive status updated';
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create archiving function to move cold data
    op.execute("""
        CREATE OR REPLACE FUNCTION archive_old_partitions(retention_months INTEGER DEFAULT 6)
        RETURNS TEXT AS $$
        DECLARE
            partition_row RECORD;
            drop_sql TEXT;
        BEGIN
            FOR partition_row IN
                SELECT
                    child.relname AS partition_name,
                    date_trunc('month', current_date) - (retention_months || ' months')::INTERVAL AS cutoff_date
                FROM pg_inherits
                JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
                JOIN pg_class child ON pg_inherits.inhrelid = child.oid
                JOIN pg_namespace n ON n.oid = parent.relnamespace
                WHERE parent.relname IN ('audit_logs', 'agent_events', 'metric_events', 'provider_runs', 'outbox_events')
                AND n.nspname = 'public'
            LOOP
                -- Extract date from partition name to check if older than retention
                -- Partition names are like: audit_logs_2026_01
                DECLARE
                    partition_date TEXT;
                    year_num INTEGER;
                    month_num INTEGER;
                    full_date DATE;
                BEGIN
                    partition_date := substring(partition_row.partition_name from position('_' in partition_row.partition_name) + 1);
                    year_num := split_part(partition_date, '_', 1)::INTEGER;
                    month_num := split_part(partition_date, '_', 2)::INTEGER;
                    full_date := make_date(year_num, month_num, 1);

                    IF full_date < partition_row.cutoff_date THEN
                        -- Detach and drop the old partition
                        EXECUTE 'ALTER TABLE ' || partition_row.partition_name || ' DETACH PARTITION;';
                        EXECUTE 'DROP TABLE ' || partition_row.partition_name || ';';
                        -- Note: In production, you would archive to S3 before dropping
                    END IF;
                EXCEPTION WHEN OTHERS THEN
                    -- Log but continue if partition name format doesn't match expected pattern
                    RAISE NOTICE 'Could not process partition: %', partition_row.partition_name;
                END;
            END LOOP;

            RETURN 'Archive cleanup completed';
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create initial monthly partitions for current month and next 2 months
    # For tables that use PARTITION BY RANGE with created_at
    partition_tables = [
        ("audit_logs", "created_at"),
        ("agent_events", "created_at"),
        ("metric_events", "recorded_at"),
        ("provider_runs", "created_at"),
        ("outbox_events", "created_at"),
    ]
    for table_name, date_col in partition_tables:
        for offset in range(3):
            op.execute(f"""
                SELECT create_monthly_partition('{table_name}', (date_trunc('month', current_date) + interval '{offset} months')::DATE);
            """)

    # Note: webhook_delivery_events and llm_prompt_cache_entries are not partitioned
    # They use partition_type='none' and rely on archive_status for lifecycle management


def downgrade() -> None:
    """Remove partition strategy columns and functions."""

    # Drop functions in reverse order of creation
    op.execute("DROP FUNCTION IF EXISTS archive_old_partitions(integer);")
    op.execute("DROP FUNCTION IF EXISTS set_archive_status();")
    op.execute("DROP FUNCTION IF EXISTS maintain_partitions();")
    op.execute("DROP FUNCTION IF EXISTS get_partition_info(text);")
    op.execute("DROP FUNCTION IF EXISTS create_future_partitions(text, integer);")
    op.execute("DROP FUNCTION IF EXISTS create_monthly_partition(text, date);")

    # Drop metadata table
    op.drop_table("partition_metadata")

    # Remove columns from all high-growth tables
    for table_name in HIGH_GROWTH_TABLES:
        op.execute(f"""
            ALTER TABLE {table_name}
            DROP COLUMN IF EXISTS partition_type,
            DROP COLUMN IF EXISTS retention_days,
            DROP COLUMN IF EXISTS archive_status;
        """)

        op.execute(f"DROP INDEX IF EXISTS ix_{table_name}_archive_status;")
