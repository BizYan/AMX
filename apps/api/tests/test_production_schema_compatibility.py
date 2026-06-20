"""Production-like historical schema compatibility gates.

These tests intentionally exercise known production drift points rather than a
clean empty-database migration path.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

asyncpg = pytest.importorskip("asyncpg")

os.environ.setdefault("JWT_SECRET_KEY", "schema-compatibility-test-secret")

from app.core.settings import settings
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.identity.models import AuditLog  # noqa: F401 - registered for create_all
from app.domains.ops.capability_activation import CapabilityActivationService
from app.domains.ops.models import AlertRule, MetricEvent, QuotaUsage
from app.domains.providers.models import (
    CapabilityType,
    Provider,
    ProviderRun,
    ProviderStatus,
    ProviderType,
    RunStatus,
)
from app.domains.providers.readiness import build_provider_readiness_summary
from app.domains.providers.registry import ProviderRegistry
from app.models.identity import Tenant


API_ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_REVISION = "0026_conflict_risk"
LEGACY_PROVIDER = "legacy-llm"
LEGACY_ERROR = "legacy timeout"


def _admin_dsn() -> str:
    return os.getenv(
        "AMX_SCHEMA_COMPAT_ADMIN_DSN",
        "postgresql://postgres:postgres@localhost:5432/postgres",
    )


def _database_url(database_name: str) -> str:
    return f"postgresql+asyncpg://postgres:postgres@localhost:5432/{database_name}"


async def _create_database(database_name: str) -> None:
    connection = await asyncpg.connect(_admin_dsn())
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await connection.close()


async def _drop_database(database_name: str) -> None:
    connection = await asyncpg.connect(_admin_dsn())
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
    finally:
        await connection.close()


@contextmanager
def temporary_postgres_database():
    database_name = f"amx_schema_compat_{uuid4().hex[:12]}"
    try:
        asyncio.run(_create_database(database_name))
    except Exception as exc:  # pragma: no cover - environment-dependent skip
        if os.getenv("CI", "").lower() == "true":
            raise
        pytest.skip(f"PostgreSQL compatibility database is unavailable: {exc}")
    try:
        yield _database_url(database_name)
    finally:
        asyncio.run(_drop_database(database_name))


def _run_alembic_upgrade_head(database_url: str) -> None:
    original_settings_url = settings.DATABASE_URL
    original_env_url = os.environ.get("DATABASE_URL")
    try:
        settings.DATABASE_URL = database_url
        os.environ["DATABASE_URL"] = database_url
        config = Config(str(API_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(API_ROOT / "alembic"))
        command.upgrade(config, "head")
    finally:
        settings.DATABASE_URL = original_settings_url
        if original_env_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_env_url


async def _create_historical_schema(database_url: str, *, include_legacy_tables: bool = True) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.execute(
                text(
                    """
                    CREATE TABLE alembic_version (
                        version_num varchar(32) NOT NULL PRIMARY KEY
                    )
                    """
                )
            )
            await connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": HISTORICAL_REVISION},
            )
            if include_legacy_tables:
                await _create_legacy_evidence_tables(connection)
    finally:
        await engine.dispose()


async def _create_legacy_evidence_tables(connection) -> None:
    await connection.execute(
        text(
            """
            CREATE TABLE provider_runs (
                id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
                tenant_id uuid NULL,
                project_id uuid NULL,
                provider varchar(50) NOT NULL,
                model varchar(100) NULL,
                input_tokens integer NULL,
                output_tokens integer NULL,
                latency_ms integer NULL,
                error text NULL,
                metadata jsonb NULL,
                created_at timestamp with time zone NOT NULL DEFAULT now()
            )
            """
        )
    )
    await connection.execute(text("CREATE INDEX ix_provider_runs_provider ON provider_runs (provider)"))
    await connection.execute(text("CREATE INDEX ix_provider_runs_created_at ON provider_runs (created_at)"))
    await connection.execute(
        text(
            """
            INSERT INTO provider_runs (
                provider, model, input_tokens, output_tokens, latency_ms, error, metadata
            )
            VALUES (:provider, 'legacy-model', 12, 4, 250, :error, '{"source":"legacy"}'::jsonb)
            """
        ),
        {"provider": LEGACY_PROVIDER, "error": LEGACY_ERROR},
    )
    await connection.execute(
        text(
            """
            CREATE TABLE metric_events (
                id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
                tenant_id uuid NULL,
                metric_name varchar(100) NOT NULL,
                metric_value double precision NOT NULL,
                metric_labels jsonb NULL,
                created_at timestamp with time zone NOT NULL DEFAULT now()
            )
            """
        )
    )
    await connection.execute(text("CREATE INDEX ix_metric_events_metric_name ON metric_events (metric_name)"))
    await connection.execute(text("CREATE INDEX ix_metric_events_created_at ON metric_events (created_at)"))
    await connection.execute(
        text(
            """
            INSERT INTO metric_events (metric_name, metric_value, metric_labels)
            VALUES ('legacy_readiness_score', 77, '{"source":"legacy"}'::jsonb)
            """
        )
    )


async def _column_map(database_url: str, table_name: str) -> dict[str, dict[str, str]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT column_name, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :table_name
                    """
                ),
                {"table_name": table_name},
            )
            return {row.column_name: {"is_nullable": row.is_nullable} for row in result}
    finally:
        await engine.dispose()


async def _table_exists(database_url: str, table_name: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT to_regclass(:table_name) IS NOT NULL AS exists"),
                {"table_name": f"public.{table_name}"},
            )
            return bool(result.scalar_one())
    finally:
        await engine.dispose()


async def _prepare_minimal_app_tables(database_url: str) -> None:
    deduplicate_indexes()
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


async def _exercise_minimal_app_paths(database_url: str) -> dict[str, object]:
    original_llm_key = os.environ.get("AMX_SCHEMA_COMPAT_LLM_KEY")
    os.environ["AMX_SCHEMA_COMPAT_LLM_KEY"] = "prod-live-compatibility-key"
    engine = create_async_engine(database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as session:
            tenant = Tenant(name="Schema Compat", slug=f"schema-compat-{uuid4().hex[:8]}")
            session.add(tenant)
            await session.flush()
            provider = Provider(
                tenant_id=tenant.id,
                name="Production LLM",
                provider_type=ProviderType.LLM.value,
                status=ProviderStatus.ACTIVE.value,
                config_json={
                    "credential_ref": "env:AMX_SCHEMA_COMPAT_LLM_KEY",
                    "base_url": "https://provider.example.invalid/v1",
                    "mode": "production",
                    "last_test_status": "healthy",
                },
                capabilities_json={"text_generation": True},
            )
            session.add(provider)
            await session.flush()

            registry = ProviderRegistry(session)
            providers, total = await registry.list_providers(tenant.id)
            readiness = build_provider_readiness_summary(tenant_id=tenant.id, providers=providers)
            provider_run = await registry.record_run(
                tenant_id=tenant.id,
                provider_id=provider.id,
                version_id=None,
                capability_type=CapabilityType.TEXT_GENERATION.value,
                input_tokens=8,
                output_tokens=5,
                latency_ms=123,
                status=RunStatus.SUCCESS,
            )
            activation_counts = await CapabilityActivationService(session)._seed_ops_observability_evidence(
                tenant.id,
                uuid4(),
            )
            await session.commit()

            current_run = await session.get(ProviderRun, provider_run.id)
            metric_events = (
                await session.execute(
                    select(MetricEvent).where(MetricEvent.tenant_id == tenant.id).order_by(MetricEvent.metric_name)
                )
            ).scalars().all()
            quota_count = len((await session.execute(select(QuotaUsage))).scalars().all())
            alert_count = len((await session.execute(select(AlertRule))).scalars().all())

            return {
                "provider_total": total,
                "readiness": readiness,
                "provider_run": current_run,
                "metric_events": metric_events,
                "activation_counts": activation_counts,
                "quota_count": quota_count,
                "alert_count": alert_count,
            }
    finally:
        if original_llm_key is None:
            os.environ.pop("AMX_SCHEMA_COMPAT_LLM_KEY", None)
        else:
            os.environ["AMX_SCHEMA_COMPAT_LLM_KEY"] = original_llm_key
        await engine.dispose()


async def _legacy_write_shapes(database_url: str, provider_run_id) -> dict[str, object]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            provider_row = (
                await connection.execute(
                    text(
                        """
                        SELECT provider, error, provider_id, capability_type, status, error_message
                        FROM provider_runs
                        WHERE id = :id
                        """
                    ),
                    {"id": provider_run_id},
                )
            ).mappings().one()
            current_metric_rows = (
                await connection.execute(
                    text(
                        """
                        SELECT metric_name, metric_value, metric_labels, metric_type, value, unit, dimensions
                        FROM metric_events
                        WHERE metric_type IN ('sla', 'agent')
                        ORDER BY metric_name
                        """
                    )
                )
            ).mappings().all()
            legacy_provider_row = (
                await connection.execute(
                    text(
                        """
                        SELECT provider, error, capability_type, status, error_message
                        FROM provider_runs
                        WHERE provider = :provider
                        """
                    ),
                    {"provider": LEGACY_PROVIDER},
                )
            ).mappings().one()
            legacy_metric_row = (
                await connection.execute(
                    text(
                        """
                        SELECT metric_name, metric_value, metric_labels, metric_type, value, unit, dimensions
                        FROM metric_events
                        WHERE metric_name = 'legacy_readiness_score'
                        """
                    )
                )
            ).mappings().one()
            return {
                "provider_row": dict(provider_row),
                "current_metric_rows": [dict(row) for row in current_metric_rows],
                "legacy_provider_row": dict(legacy_provider_row),
                "legacy_metric_row": dict(legacy_metric_row),
            }
    finally:
        await engine.dispose()


def test_historical_provider_and_metric_schema_upgrade_supports_current_app_writes():
    with temporary_postgres_database() as database_url:
        asyncio.run(_create_historical_schema(database_url, include_legacy_tables=True))

        _run_alembic_upgrade_head(database_url)

        provider_columns = asyncio.run(_column_map(database_url, "provider_runs"))
        metric_columns = asyncio.run(_column_map(database_url, "metric_events"))
        assert {"provider", "error", "provider_id", "capability_type", "status", "error_message"} <= set(
            provider_columns
        )
        assert {"metric_value", "metric_labels", "metric_type", "value", "unit", "dimensions"} <= set(metric_columns)
        assert provider_columns["provider"]["is_nullable"] == "YES"
        assert metric_columns["metric_value"]["is_nullable"] == "YES"

        asyncio.run(_prepare_minimal_app_tables(database_url))
        result = asyncio.run(_exercise_minimal_app_paths(database_url))

        assert Provider.runs.property.lazy == "noload"
        assert result["provider_total"] == 1
        assert result["readiness"].production_ready is True
        assert result["readiness"].missing_required_types == []
        assert result["provider_run"].capability_type == CapabilityType.TEXT_GENERATION.value
        assert result["provider_run"].status == RunStatus.SUCCESS.value
        assert {event.metric_name for event in result["metric_events"]} == {
            "core_loop_readiness_score",
            "workflow_success_rate",
        }
        assert result["activation_counts"]["metric_event_count"] >= 2
        assert result["quota_count"] == 2
        assert result["alert_count"] == 1

        write_shapes = asyncio.run(_legacy_write_shapes(database_url, result["provider_run"].id))
        assert write_shapes["provider_row"]["provider"] is None
        assert write_shapes["provider_row"]["error"] is None
        assert write_shapes["provider_row"]["provider_id"] == result["provider_run"].provider_id
        assert all(row["metric_value"] is None for row in write_shapes["current_metric_rows"])
        assert all(row["metric_type"] in {"sla", "agent"} for row in write_shapes["current_metric_rows"])
        assert write_shapes["legacy_provider_row"]["provider"] == LEGACY_PROVIDER
        assert write_shapes["legacy_provider_row"]["error"] == LEGACY_ERROR
        assert write_shapes["legacy_provider_row"]["capability_type"] == LEGACY_PROVIDER
        assert write_shapes["legacy_provider_row"]["error_message"] == LEGACY_ERROR
        assert write_shapes["legacy_metric_row"]["metric_value"] == 77
        assert write_shapes["legacy_metric_row"]["metric_type"] == "system"
        assert write_shapes["legacy_metric_row"]["value"] == 77


def test_historical_schema_upgrade_skips_missing_legacy_tables_safely():
    with temporary_postgres_database() as database_url:
        asyncio.run(_create_historical_schema(database_url, include_legacy_tables=False))

        _run_alembic_upgrade_head(database_url)

        assert asyncio.run(_table_exists(database_url, "provider_runs")) is False
        assert asyncio.run(_table_exists(database_url, "metric_events")) is False
