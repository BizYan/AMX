# AMX Recovery Drill Runbook

Purpose: prove AMX can recover through backup restore and application rollback
without destructive database downgrade.

This runbook is mandatory before the first real client and after any migration,
deployment, Docker, or provider operations change that could affect recovery.
It is a controlled drill, not a production restore procedure.

## Safety Boundaries

- Do not restore production data without explicit Owner Go.
- Do not run destructive database downgrade during this drill.
- Do not use customer data.
- Do not print, copy, or commit `.env` files, access tokens, passwords, API
  keys, private keys, or database dumps.
- Preserve the current production rollback procedure in
  `docs/runbooks/v1.0-rollback.md` and `docs/runbooks/oci-operations.md`.
- Use only isolated staging/candidate Docker Compose project names,
  non-production ports, non-production networks, isolated volumes, and an
  isolated database name.

## Required Evidence

Record the following in the drill report:

- drill date and operator;
- repository SHA and known-good rollback ref;
- source backup project name, database name, backup file name, size, and SHA256;
- restore project name, database name, ports, network, and volumes;
- restore command exit status;
- application startup result;
- health result;
- authenticated smoke result;
- key project/document data verification result;
- application rollback ref and rollback command;
- post-rollback health, authenticated smoke, service status, and provenance
  result;
- elapsed time for backup, restore, startup, rollback, and full drill;
- owner decision points and unresolved risks.

## Inputs

Set these variables in the shell running the drill. Values below are examples;
replace them with isolated values for each run.

```bash
export DRILL_SHA="$(git rev-parse HEAD)"
export SHORT_SHA="${DRILL_SHA:0:12}"
export BACKUP_PROJECT="amx_drill_backup_${SHORT_SHA}"
export RESTORE_PROJECT="amx_drill_restore_${SHORT_SHA}"
export BACKUP_CONTAINER_PREFIX="$BACKUP_PROJECT"
export RESTORE_CONTAINER_PREFIX="$RESTORE_PROJECT"
export RESTORE_REF="v1.0.2"
export DRILL_ROOT="$HOME/amx/recovery-drills/$SHORT_SHA"
export BACKUP_FILE="$DRILL_ROOT/amx-${SHORT_SHA}.dump"
export BACKUP_SHA_FILE="$BACKUP_FILE.sha256"
```

The rollback ref must be a release tag or immutable SHA that is reachable from
the repository and approved for the drill. Do not use an unreviewed branch.

Both `$DRILL_ROOT/.env.backup` and `$DRILL_ROOT/.env.restore` must be
drill-only files, not production `.env`. Each file must set isolated values for
`COMPOSE_PROJECT_NAME`, `AMX_ENV_FILE`, `AMX_CONTAINER_PREFIX`,
`AMX_RUNTIME_NETWORK`, `AMX_POSTGRES_VOLUME`, `AMX_REDIS_VOLUME`,
`POSTGRES_DB`, `POSTGRES_HOST_PORT`, `REDIS_HOST_PORT`, `API_HOST_PORT`, and
`WEB_HOST_PORT`. For the examples below, `AMX_CONTAINER_PREFIX` must equal
`$BACKUP_CONTAINER_PREFIX` or `$RESTORE_CONTAINER_PREFIX` respectively.

## Phase 1: Create Disposable Source Backup

Use a disposable staging or candidate environment. Do not use production unless
Owner Go explicitly authorizes a production backup drill.

1. Start or identify an isolated source stack.
2. Seed one synthetic project and one synthetic document with a unique marker.
3. Confirm the marker is visible through authenticated API reads.
4. Create a custom-format PostgreSQL backup.

Example command shape:

```bash
mkdir -p "$DRILL_ROOT"

docker compose \
  -p "$BACKUP_PROJECT" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.candidate.yml \
  --env-file "$DRILL_ROOT/.env.backup" \
  exec -T postgres \
  pg_dump -Fc \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -f "/tmp/amx-${SHORT_SHA}.dump"

docker cp \
  "${BACKUP_CONTAINER_PREFIX}_postgres:/tmp/amx-${SHORT_SHA}.dump" \
  "$BACKUP_FILE"

sha256sum "$BACKUP_FILE" | tee "$BACKUP_SHA_FILE"
ls -lh "$BACKUP_FILE"
```

Evidence required:

- source compose project;
- source database name;
- synthetic marker;
- backup file size;
- backup SHA256;
- confirmation that no customer data was used.

## Phase 2: Restore Into Isolated Disposable Environment

Restore the backup into a separate isolated project. The restore project must
not share ports, network, volumes, or database name with the source or
production stack.

1. Generate a restore-only env file.
2. Run candidate safety validation against the rendered compose config.
3. Start only PostgreSQL and Redis.
4. Copy the backup into the restore PostgreSQL container.
5. Restore into the empty isolated restore database.

Example command shape:

```bash
docker compose \
  -p "$RESTORE_PROJECT" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.candidate.yml \
  --env-file "$DRILL_ROOT/.env.restore" \
  config > "$DRILL_ROOT/restore-compose-config.yml"

bash infra/deploy/validate-candidate-verification.sh \
  --env-file "$DRILL_ROOT/.env.restore" \
  --compose-project-name "$RESTORE_PROJECT" \
  --compose-config "$DRILL_ROOT/restore-compose-config.yml"

docker compose \
  -p "$RESTORE_PROJECT" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.candidate.yml \
  --env-file "$DRILL_ROOT/.env.restore" \
  up -d postgres redis

docker cp "$BACKUP_FILE" "${RESTORE_CONTAINER_PREFIX}_postgres:/tmp/restore.dump"

docker compose \
  -p "$RESTORE_PROJECT" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.candidate.yml \
  --env-file "$DRILL_ROOT/.env.restore" \
  exec -T postgres \
  pg_restore \
    --no-owner \
    --role "$POSTGRES_USER" \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    "/tmp/restore.dump"
```

Evidence required:

- restore compose project;
- restore database name;
- rendered-config safety validation output;
- restore exit status;
- list of restored schema/table counts sufficient to prove data exists.

## Phase 3: Verify Restored Application

Start the API against the restored database, then verify health, authenticated
smoke, and key data.

```bash
docker compose \
  -p "$RESTORE_PROJECT" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.candidate.yml \
  --env-file "$DRILL_ROOT/.env.restore" \
  up -d --build api

docker compose \
  -p "$RESTORE_PROJECT" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.candidate.yml \
  --env-file "$DRILL_ROOT/.env.restore" \
  exec -T api sh -c \
  'nohup /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 > /proc/1/fd/1 2> /proc/1/fd/2 &'

for attempt in {1..30}; do
  if curl -fsS "http://127.0.0.1:$API_HOST_PORT/health"; then
    echo "[recovery-drill] restored health passed"
    break
  fi
  sleep 3
done

bash infra/deploy/authenticated-smoke.sh \
  --base-url "http://127.0.0.1:$API_HOST_PORT" \
  --env-file "$DRILL_ROOT/.env.restore"
```

Verify key project/document data through authenticated API calls. The drill must
prove that the synthetic marker survived backup and restore.

Evidence required:

- restored health output;
- authenticated smoke output;
- project ID and document ID for synthetic data;
- marker verification result;
- service status from `docker compose ps`.

## Phase 4: Application Rollback Without Database Downgrade

Rollback application code in the disposable restore environment only. Do not
run Alembic downgrade. The purpose is to prove that a known-good application ref
can start against the restored database, or to identify compatibility blockers
before any production incident.

Recommended command shape from a separate disposable checkout:

```bash
git fetch origin --prune --tags
git checkout --force "$RESTORE_REF"

docker compose \
  -p "$RESTORE_PROJECT" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.candidate.yml \
  --env-file "$DRILL_ROOT/.env.restore" \
  up -d --build api worker web

docker compose \
  -p "$RESTORE_PROJECT" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.candidate.yml \
  --env-file "$DRILL_ROOT/.env.restore" \
  exec -T api sh -c \
  'nohup /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 > /proc/1/fd/1 2> /proc/1/fd/2 &'

docker compose \
  -p "$RESTORE_PROJECT" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.candidate.yml \
  --env-file "$DRILL_ROOT/.env.restore" \
  ps

bash infra/deploy/authenticated-smoke.sh \
  --base-url "http://127.0.0.1:$API_HOST_PORT" \
  --env-file "$DRILL_ROOT/.env.restore"
```

For non-production provenance, record:

```bash
git rev-parse HEAD
git rev-parse "${RESTORE_REF}^{commit}"
docker compose \
  -p "$RESTORE_PROJECT" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.candidate.yml \
  --env-file "$DRILL_ROOT/.env.restore" \
  ps --status running
```

Evidence required:

- rollback ref;
- checked-out SHA;
- health output;
- authenticated smoke output;
- running services;
- data marker still present;
- explicit confirmation that no database downgrade ran.

## Phase 5: Teardown

Always tear down the disposable stack and delete temporary env/config files.
Retain only sanitized reports, command transcript summaries, backup checksum,
and non-secret metadata.

```bash
docker compose \
  -p "$RESTORE_PROJECT" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.candidate.yml \
  --env-file "$DRILL_ROOT/.env.restore" \
  down -v --remove-orphans

docker compose \
  -p "$BACKUP_PROJECT" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.candidate.yml \
  --env-file "$DRILL_ROOT/.env.backup" \
  down -v --remove-orphans

rm -f "$DRILL_ROOT/.env.backup" "$DRILL_ROOT/.env.restore" "$DRILL_ROOT/restore-compose-config.yml"
```

Evidence required:

- post-teardown containers;
- post-teardown networks;
- post-teardown volumes;
- list of retained sanitized artifacts.

## Owner Decision Points

Owner decision is required before:

- using any production backup as drill input;
- restoring any data that may contain customer or regulated content;
- accepting a rollback ref that fails health or authenticated smoke but might
  still be needed for incident containment;
- running any database downgrade;
- changing the production rollback procedure.

## Drill Report Template

```markdown
# AMX Recovery Drill Report

- Date:
- Operator:
- Repository SHA:
- Source project:
- Restore project:
- Rollback ref:
- Customer data used: no
- Production touched: no
- Database downgrade run: no

## Backup Evidence
- Backup file:
- Size:
- SHA256:
- Source DB:
- Synthetic marker:

## Restore Evidence
- Restore DB:
- Restore command:
- Exit status:
- Schema/table evidence:

## Application Verification
- Startup:
- Health:
- Authenticated smoke:
- Project/document marker:
- Service status:

## Rollback Verification
- Rollback ref:
- Checked-out SHA:
- Health:
- Authenticated smoke:
- Service status:
- Data preserved:
- Provenance:

## Elapsed Time
- Backup:
- Restore:
- Startup:
- Rollback:
- Full drill:

## Owner Decisions
- Decisions made:
- Deferred decisions:

## Unresolved Risks
-
```
