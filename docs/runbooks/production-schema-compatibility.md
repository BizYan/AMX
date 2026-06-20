# Production Schema Compatibility

AMX production migration safety must cover production-like historical schema
drift, not only clean empty-database upgrades.

## Purpose

This gate prevents deployment failures caused by current ORM models reading or
writing columns that are absent, renamed, or still constrained in older
production databases.

The current compatibility fixture represents the known production drift fixed by
PR #151 through PR #153:

- `provider_runs.provider`
- `provider_runs.error`
- `metric_events.metric_value`
- `metric_events.metric_labels`

These legacy columns must be preserved. They must not block current writes that
use the current ORM columns:

- `provider_runs.provider_id`
- `provider_runs.version_id`
- `provider_runs.capability_type`
- `provider_runs.status`
- `provider_runs.error_message`
- `provider_runs.updated_at`
- `metric_events.metric_type`
- `metric_events.value`
- `metric_events.unit`
- `metric_events.dimensions`
- `metric_events.recorded_at`
- `metric_events.updated_at`

## Required Gate

Run:

```powershell
uv run --directory apps/api --extra dev python -m pytest tests/test_production_schema_compatibility.py -q
```

The test creates a disposable PostgreSQL database, creates the historical
production-like fixture, stamps `0026_conflict_risk`, runs `alembic upgrade
head`, and then exercises minimal current application DB paths.

The gate verifies:

- provider readiness does not auto-load `provider_runs` history;
- `ProviderRun` can be written with the current shape;
- `MetricEvent` can be written with the current shape;
- capability activation can write ops observability evidence;
- legacy columns remain present;
- legacy NOT NULL constraints no longer block current writes;
- missing historical tables are skipped safely for candidate-baseline
  environments.

## Adding Future Drift

When production reveals another historical schema drift:

1. Add the legacy table or column to the fixture in
   `tests/test_production_schema_compatibility.py`.
2. Add a non-destructive Alembic migration that preserves legacy data.
3. Prove both legacy-row preservation and current ORM read/write behavior.
4. Add the drift to this runbook.
5. Do not remove legacy columns or destructively downgrade production data.

## Evidence Boundaries

This compatibility gate is production-like schema evidence. It is not a
replacement for:

- clean empty-database migration checks;
- isolated candidate verification;
- production deployment health;
- authenticated production smoke;
- deployment provenance.

All release promotions still require the full release and production gates.
