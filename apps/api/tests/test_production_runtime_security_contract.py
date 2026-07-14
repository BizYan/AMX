"""Production runtime network and deployment-security contract checks."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def workflow_run_blocks(workflow: str) -> list[str]:
    blocks: list[str] = []
    lines = workflow.splitlines()

    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if not (stripped.startswith("run: |") or stripped.startswith("run: >")):
            continue

        parent_indent = len(line) - len(stripped)
        block_lines: list[str] = []
        for candidate in lines[index + 1 :]:
            if not candidate.strip():
                block_lines.append(candidate)
                continue
            candidate_indent = len(candidate) - len(candidate.lstrip())
            if candidate_indent <= parent_indent:
                break
            block_lines.append(candidate)
        blocks.append("\n".join(block_lines))

    return blocks


def test_runtime_ports_bind_to_loopback_by_default():
    compose = read("infra/docker-compose.yml")

    for variable, port in (
        ("POSTGRES_BIND_ADDRESS", "15432"),
        ("REDIS_BIND_ADDRESS", "16379"),
        ("API_BIND_ADDRESS", "18000"),
        ("WEB_BIND_ADDRESS", "3000"),
    ):
        assert f"${{{variable}:-127.0.0.1}}" in compose
        assert f"${{{variable.replace('BIND_ADDRESS', 'HOST_PORT')}:-{port}}}" in compose


def test_runtime_containers_use_internal_redis_service_by_default():
    compose = read("infra/docker-compose.yml")

    assert compose.count("REDIS_URL: ${CONTAINER_REDIS_URL:-redis://redis:6379/0}") == 2
    assert compose.count("ARQ_REDIS_URL: ${CONTAINER_ARQ_REDIS_URL:-redis://redis:6379/1}") == 2


def test_base_compose_keeps_production_defaults_but_allows_candidate_isolation():
    compose = read("infra/docker-compose.yml")

    for service in ("postgres", "redis", "api", "worker", "web"):
        assert f"container_name: ${{AMX_CONTAINER_PREFIX:-consultant_ai}}_{service}" in compose

    assert "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB" in compose
    assert "pg_isready -U consultant -d consultant_ai" not in compose
    assert compose.count("${AMX_ENV_FILE:-../.env}") == 3
    assert "name: ${AMX_RUNTIME_NETWORK:-amx_runtime_network}" in compose


def test_candidate_compose_override_replaces_env_and_disables_restarts():
    candidate = read("infra/docker-compose.candidate.yml")

    assert candidate.count("${AMX_ENV_FILE:?AMX_ENV_FILE must point to the candidate env file}") == 3
    assert candidate.count('restart: "no"') == 3
    assert 'command: ["sh", "-c", "sleep infinity"]' in candidate
    assert "${AMX_POSTGRES_VOLUME:?AMX_POSTGRES_VOLUME must be candidate scoped}" in candidate
    assert "${AMX_REDIS_VOLUME:?AMX_REDIS_VOLUME must be candidate scoped}" in candidate
    assert "../.env" not in candidate


def test_candidate_safety_script_fails_closed_before_compose_up():
    script = read("infra/deploy/validate-candidate-verification.sh")

    for required in (
        "--env-file",
        "--compose-project-name",
        "candidate env file must not be production .env",
        "COMPOSE_PROJECT_NAME must start with amx_rc_",
        "POSTGRES_DB must not be production database",
        "AMX_RUNTIME_NETWORK must be candidate scoped",
        "AMX_POSTGRES_VOLUME must be candidate scoped",
        "AMX_REDIS_VOLUME must be candidate scoped",
        "must not use production port",
        "working directory must not be production path",
        "candidate compose config must not reference ../.env",
        "candidate compose config must not include production container names",
        "candidate compose config must not bind production ports",
        "candidate API/worker/web restart policy must be no",
    ):
        assert required in script


def test_candidate_verification_workflow_is_manual_and_non_production():
    workflow = read(".github/workflows/candidate-verification.yml")

    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert "pull_request:" not in workflow
    assert "environment: release-candidate" in workflow
    assert "REQUESTED_CANDIDATE_SHA: ${{ inputs.ref }}" in workflow
    assert "concurrency:" in workflow
    assert "secrets.RELEASE_CANDIDATE_BOOTSTRAP_ADMIN_EMAIL" in workflow
    assert "secrets.RELEASE_CANDIDATE_BOOTSTRAP_ADMIN_PASSWORD" in workflow
    assert "secrets.RELEASE_CANDIDATE_LLM_API_KEY" in workflow
    assert "AMX_CANDIDATE_LLM_API_KEY=$RELEASE_CANDIDATE_LLM_API_KEY" in workflow
    assert "AMX_CANDIDATE_GRAPHIFY_READINESS_REF=internal-candidate-graphify-ready" in workflow
    assert "AMX_CANDIDATE_GITNEXUS_READINESS_REF=internal-candidate-gitnexus-ready" in workflow
    assert "Commission candidate provider readiness" in workflow
    assert "Activate candidate capability evidence" in workflow
    assert "/api/v1/ops/capabilities/activation-run" in workflow
    assert "candidate-capability-activation.json" in workflow
    assert "Run candidate authenticated smoke" in workflow
    assert workflow.index("Activate candidate capability evidence") < workflow.index(
        "Run candidate authenticated smoke"
    )
    assert '"dry_run":false,"confirm":true' in workflow
    assert '"credential_ref": "env:AMX_CANDIDATE_LLM_API_KEY"' in workflow
    assert '"credential_ref": "env:AMX_CANDIDATE_GRAPHIFY_READINESS_REF"' in workflow
    assert '"credential_ref": "env:AMX_CANDIDATE_GITNEXUS_READINESS_REF"' in workflow
    assert "secrets.PRODUCTION" not in workflow
    assert "OCI_" not in workflow
    assert "gh release" not in workflow
    assert "git tag" not in workflow
    assert "deploy-production" not in workflow
    assert "git worktree add" not in workflow
    assert "Overlay verification infrastructure" not in workflow
    assert "cp infra/docker-compose.yml" not in workflow
    assert "compose_project_name" not in workflow
    assert "default: \"1877e0b4a0cd208890391b76afc8c5f23647cd3b\"" not in workflow
    assert "fetch-depth: 0" in workflow
    assert 'test "$CHECKED_OUT_SHA" = "$REQUESTED_CANDIDATE_SHA"' in workflow
    assert 'git merge-base --is-ancestor "$CHECKED_OUT_SHA" origin/main' in workflow
    assert 'echo "CANDIDATE_SHA=$CHECKED_OUT_SHA" >> "$GITHUB_ENV"' in workflow
    assert 'PROJECT_NAME="amx_rc_${SHORT_SHA}"' in workflow
    assert 'CANDIDATE_ENV_FILE=$RUNNER_TEMP/.env.rc.${SHORT_SHA}' in workflow
    assert "test -f infra/docker-compose.candidate.yml" in workflow
    assert "test -f infra/deploy/validate-candidate-verification.sh" in workflow
    assert 'exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' in workflow
    assert 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";' in workflow
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in workflow
    assert "CREATE TABLE IF NOT EXISTS projects (" in workflow
    assert "owner_id uuid" in workflow
    assert "status varchar(20) NOT NULL DEFAULT" in workflow
    assert "CREATE TABLE IF NOT EXISTS documents (" in workflow
    assert "project_id uuid NOT NULL" in workflow
    assert "metadata_json jsonb" in workflow
    assert "Verify historical migration compatibility baseline" in workflow
    assert "historical migration compatibility baseline verification" in workflow
    assert "not a clean empty-database full-history migration proof" in workflow
    assert "/app/.venv/bin/alembic stamp 0021_invitation_delivery" in workflow
    assert (
        "/app/.venv/bin/alembic upgrade head"
    ) in workflow
    assert (
        "/app/.venv/bin/alembic downgrade 0021_invitation_delivery"
    ) in workflow
    assert (
        "/app/.venv/bin/alembic upgrade head"
    ) in workflow
    assert "authenticated-smoke.sh" in workflow
    assert "Start candidate API server" in workflow
    assert "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1" in workflow
    assert "down -v --remove-orphans" in workflow
    assert "remaining_containers" in workflow
    assert "up -d --build postgres redis api" in workflow
    assert "up -d --build\n" not in workflow
    assert "runtime_started=postgres,redis,api" in workflow
    assert "config_isolated_not_runtime_started=worker,web" in workflow
    assert "remaining_networks" in workflow
    assert "remaining_volumes" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "path: artifacts" in workflow
    artifact_section = workflow.split("path: artifacts", 1)[1]
    assert "candidate-compose-config" not in artifact_section
    assert ".env.rc." not in artifact_section
    assert "candidate-compose-logs-redacted.txt" in workflow
    assert "docker compose run --rm api" not in workflow
    assert "exec -T api" in workflow
    assert workflow.count("-f infra/docker-compose.candidate.yml") >= 8


def test_candidate_workflow_shell_run_blocks_do_not_interpolate_github_inputs():
    workflow = read(".github/workflows/candidate-verification.yml")
    run_blocks = workflow_run_blocks(workflow)

    assert run_blocks
    forbidden = ("${{ github.event.inputs.ref }}", "${{ inputs.ref }}")
    offenders = [
        block
        for block in run_blocks
        if any(expression in block for expression in forbidden)
    ]

    assert offenders == []


def test_candidate_workflow_ref_enters_bash_only_through_requested_sha_env():
    workflow = read(".github/workflows/candidate-verification.yml")
    run_blocks = workflow_run_blocks(workflow)

    assert "REQUESTED_CANDIDATE_SHA: ${{ inputs.ref }}" in workflow
    assert "ref: ${{ inputs.ref }}" in workflow
    assert "${{ github.event.inputs.ref }}" not in workflow

    verify_block = next(
        block
        for block in run_blocks
        if '[[ "$REQUESTED_CANDIDATE_SHA" =~ ^[0-9a-f]{40}$ ]]' in block
    )
    assert "${{ inputs.ref }}" not in verify_block
    assert 'test "$CHECKED_OUT_SHA" = "$REQUESTED_CANDIDATE_SHA"' in verify_block
    assert 'echo "CANDIDATE_SHA=$CHECKED_OUT_SHA" >> "$GITHUB_ENV"' in verify_block


def test_candidate_workflow_derives_resources_from_verified_sha():
    workflow = read(".github/workflows/candidate-verification.yml")

    assert 'CHECKED_OUT_SHA="$(git rev-parse HEAD)"' in workflow
    assert 'test "$CHECKED_OUT_SHA" = "$REQUESTED_CANDIDATE_SHA"' in workflow
    assert 'echo "CANDIDATE_SHA=$CHECKED_OUT_SHA" >> "$GITHUB_ENV"' in workflow
    assert 'SHORT_SHA="${CANDIDATE_SHA:0:12}"' in workflow
    assert 'PROJECT_NAME="amx_rc_${SHORT_SHA}"' in workflow
    assert 'echo "candidate_sha=$CANDIDATE_SHA"' in workflow
    assert 'SHORT_SHA="${REQUESTED_CANDIDATE_SHA:0:12}"' not in workflow
    assert 'PROJECT_NAME="amx_rc_${REQUESTED_CANDIDATE_SHA' not in workflow


def test_staging_workflow_is_manual_exact_sha_only_and_shell_input_safe():
    workflow = read(".github/workflows/deploy-staging.yml")
    run_blocks = workflow_run_blocks(workflow)

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "REQUESTED_STAGING_SHA: ${{ inputs.ref }}" in workflow
    assert "ref: ${{ inputs.ref }}" in workflow
    assert '[[ "$REQUESTED_STAGING_SHA" =~ ^[0-9a-f]{40}$ ]]' in workflow
    assert 'test "$CHECKED_OUT_SHA" = "$REQUESTED_STAGING_SHA"' in workflow
    assert 'git merge-base --is-ancestor "$CHECKED_OUT_SHA" origin/main' in workflow

    forbidden = ("${{ github.event.inputs.ref }}", "${{ inputs.ref }}")
    assert [block for block in run_blocks if any(value in block for value in forbidden)] == []


def test_staging_workflow_fails_closed_and_isolates_runtime_resources():
    workflow = read(".github/workflows/deploy-staging.yml")

    assert "environment: staging" in workflow
    assert "environment: production" not in workflow
    assert "STAGING_LLM_API_KEY: ${{ secrets.STAGING_LLM_API_KEY }}" in workflow
    assert 'test -n "$STAGING_LLM_API_KEY"' in workflow
    assert 'COMPOSE_PROJECT_NAME="amx_staging_${SLOT_KEY}_${SHORT_SHA}"' in workflow
    assert 'echo "AMX_RUNTIME_NETWORK=${COMPOSE_PROJECT_NAME}_network"' in workflow
    assert 'echo "POSTGRES_DB=$COMPOSE_PROJECT_NAME"' in workflow
    assert "POSTGRES_HOST_PORT=$((30000 + PORT_OFFSET))" in workflow
    assert "REDIS_HOST_PORT=$((31000 + PORT_OFFSET))" in workflow
    assert "API_HOST_PORT=$((32000 + PORT_OFFSET))" in workflow
    assert "WEB_HOST_PORT=$((33000 + PORT_OFFSET))" in workflow
    assert "isolated staging port is already in use" in workflow
    assert "staging root is outside the approved path" in workflow
    assert 'ALLOWED_CORS_ORIGINS="http://127.0.0.1:23000"' in workflow
    assert 'test -n "$STAGING_NEXT_PUBLIC_API_URL"' in workflow
    assert "AMX_RESTART_POLICY=no" in workflow
    assert "Validate staging isolation before startup" in workflow
    assert "validate-staging-isolation.sh" in workflow
    assert r'--env-file \"$REMOTE_SLOT_PATH/.env\"' in workflow
    assert r'--compose-project-name \"$COMPOSE_PROJECT_NAME\"' in workflow
    assert "/home/ubuntu/amx/production" not in workflow


def test_staging_real_browser_gate_uses_real_runtime_and_tears_down():
    workflow = read(".github/workflows/deploy-staging.yml")

    assert 'RUN_REAL_BROWSER_DELIVERY_TEST: "true"' in workflow
    assert "E2E_TARGET: staging" in workflow
    assert "real-browser-commercial-delivery.spec.ts" in workflow
    assert "--trace=off" in workflow
    assert "setupApiMocks" not in workflow
    assert "page.route" not in workflow
    assert "mock-jwt" not in workflow
    assert "down -v --remove-orphans" in workflow
    assert 'rm -f .env .env.pending' in workflow
    assert 'test -z "$remaining_containers$remaining_networks$remaining_volumes"' in workflow
    assert 'label=com.docker.compose.project=$project_name' in workflow
    assert "staging-container-status.txt" in workflow
    assert "production container is still owned by a staging path" in workflow
    assert "staging-commercial-journey-evidence" in workflow


def test_staging_isolation_validator_fails_closed_on_production_resources():
    script = read("infra/deploy/validate-staging-isolation.sh")

    for required in (
        "working directory must be inside the approved staging root",
        "/home/ubuntu/amx/production/AMX",
        "^amx_staging_",
        "AMX_CONTAINER_PREFIX",
        "AMX_RUNTIME_NETWORK",
        "POSTGRES_DB",
        "AMX_RESTART_POLICY",
        "staging must not use a production port",
        "rendered staging config references production resources",
        "staging Compose project already has containers",
        "production container is owned by a staging working directory",
        "staging_isolation=passed",
    ):
        assert required in script

    assert '--env-file "$env_file"' in script
    assert '-p "$COMPOSE_PROJECT_NAME"' in script


@pytest.mark.skipif(os.name == "nt" or shutil.which("docker") is None, reason="requires Linux Docker Compose")
def test_staging_isolation_validator_executes_against_rendered_compose(tmp_path: Path):
    staging_root = tmp_path / "staging"
    working_directory = staging_root / "contract-slot"
    infra_directory = working_directory / "infra"
    infra_directory.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "infra/docker-compose.yml", infra_directory / "docker-compose.yml")
    shutil.copy2(REPO_ROOT / "infra/init-db.sql", infra_directory / "init-db.sql")

    project_name = "amx_staging_contract_slot_0123456789ab"
    env_file = working_directory / ".env"
    env_file.write_text(
        "\n".join(
            (
                "ENVIRONMENT=staging",
                f"COMPOSE_PROJECT_NAME={project_name}",
                f"AMX_ENV_FILE={env_file}",
                f"AMX_CONTAINER_PREFIX={project_name}",
                f"AMX_RUNTIME_NETWORK={project_name}_network",
                "AMX_RESTART_POLICY=no",
                "POSTGRES_USER=consultant",
                "POSTGRES_PASSWORD=synthetic-staging-password",
                f"POSTGRES_DB={project_name}",
                "POSTGRES_HOST_PORT=30123",
                "REDIS_HOST_PORT=31123",
                "API_HOST_PORT=32123",
                "WEB_HOST_PORT=33123",
                "DATABASE_URL=postgresql+asyncpg://consultant:synthetic-staging-password@postgres:5432/staging",
                "REDIS_URL=redis://redis:6379/0",
                "ARQ_REDIS_URL=redis://redis:6379/1",
                "NEXT_PUBLIC_API_URL=http://127.0.0.1:28000/api/v1",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    command = [
        "bash",
        str(REPO_ROOT / "infra/deploy/validate-staging-isolation.sh"),
        "--env-file",
        str(env_file),
        "--compose-project-name",
        project_name,
        "--working-directory",
        str(working_directory),
        "--staging-root",
        str(staging_root),
    ]
    environment = os.environ.copy()
    environment["AMX_APPROVED_STAGING_ROOT"] = str(staging_root.resolve())
    result = subprocess.run(command, capture_output=True, text=True, env=environment, check=False)

    assert result.returncode == 0, result.stderr
    assert "staging_isolation=passed" in result.stdout

    unsafe_env = env_file.read_text(encoding="utf-8").replace(
        f"AMX_CONTAINER_PREFIX={project_name}", "AMX_CONTAINER_PREFIX=consultant_ai"
    )
    env_file.write_text(unsafe_env, encoding="utf-8")
    rejected = subprocess.run(command, capture_output=True, text=True, env=environment, check=False)

    assert rejected.returncode != 0
    assert "staging isolation mismatch: AMX_CONTAINER_PREFIX" in rejected.stderr


def test_staging_workflow_does_not_interpolate_secrets_in_shell_blocks():
    workflow = read(".github/workflows/deploy-staging.yml")

    assert all("${{ secrets." not in block for block in workflow_run_blocks(workflow))


def test_real_browser_commercial_journey_uses_ui_roles_and_sanitized_artifacts():
    spec = read("apps/web/tests/e2e/playwright/real-browser-commercial-delivery.spec.ts")
    config = read("apps/web/playwright.config.ts")

    assert "setupApiMocks" not in spec
    assert "page.route(" not in spec
    assert "apiJson<any>(request, 'post', '/projects'" not in spec
    assert "open-project-launch" in spec
    assert "Project Lead" in spec
    assert "Reviewer" in spec
    assert "Approver" in spec
    assert "document-submit-review-action" in spec
    assert "create-baseline-action" in spec
    assert "waitForEvent('download')" in spec
    assert "portal-unavailable" in spec
    assert "project.acceptance.close" in spec
    assert "commercial-delivery-evidence.json" in spec
    assert "portalUrl" not in spec.split("type JourneyEvidence", 1)[1].split("}", 1)[0]
    assert "runRealBrowserDelivery ? 'off' : 'on-first-retry'" in config
    assert "runRealBrowserDelivery ? 'off' : 'only-on-failure'" in config
    assert "runRealBrowserDelivery ? 'off' : 'retain-on-failure'" in config


def test_candidate_migration_gate_claim_matches_implementation_and_docs():
    workflow = read(".github/workflows/candidate-verification.yml")
    release_runbook = read("docs/runbooks/release-management.md")
    blocker = read("docs/programs/v1.0-release-promotion-blocker.md")

    for document in (workflow, release_runbook, blocker):
        assert "historical migration compatibility baseline verification" in document
        assert "clean empty-database full-history migration proof" in document

    assert "Verify disposable PostgreSQL migration cycle" not in workflow
    assert "Disposable PostgreSQL Migration Upgrade Verification" not in blocker
    assert "/app/.venv/bin/alembic stamp 0021_invitation_delivery" in workflow
    assert "/app/.venv/bin/alembic downgrade 0021_invitation_delivery" in workflow
    assert "baseline_fixture=0021_invitation_delivery plus projects/documents ORM smoke columns" in workflow


def test_candidate_runtime_scope_remains_api_only_at_runtime():
    workflow = read(".github/workflows/candidate-verification.yml")
    release_runbook = read("docs/runbooks/release-management.md")
    blocker = read("docs/programs/v1.0-release-promotion-blocker.md")

    assert "up -d --build postgres redis api" in workflow
    assert "up -d --build postgres redis api worker" not in workflow
    assert "up -d --build postgres redis api web" not in workflow
    assert "runtime_started=postgres,redis,api" in workflow
    assert "config_isolated_not_runtime_started=worker,web" in workflow
    assert "runtime startup scope is intentionally limited to `postgres`" in release_runbook
    assert "runtime-start only `postgres`, `redis`, and `api`" in blocker


def test_runtime_containers_receive_explicit_environment():
    compose = read("infra/docker-compose.yml")
    deploy = read("infra/deploy/deploy-oci.sh")

    assert compose.count("ENVIRONMENT: ${ENVIRONMENT:-development}") == 2
    assert "export ENVIRONMENT" in deploy
    assert 'COMPOSE_COMMAND=(docker compose --env-file "$ENV_FILE")' in deploy
    assert 'COMPOSE_COMMAND+=(-p "$COMPOSE_PROJECT_NAME_OVERRIDE")' in deploy
    assert '"${COMPOSE_COMMAND[@]}" config --quiet' in deploy
    assert "/tmp/amx-compose-config.yml" not in deploy
    assert "Non-production deployment requires explicit --env-file and --compose-project-name" in deploy
    assert "Non-production Compose project name must not use a production identity" in deploy
    assert "Non-production env file must stay inside its deployment path" in deploy
    assert deploy.index("export ENVIRONMENT") < deploy.index("COMPOSE_COMMAND=(docker compose")
    assert compose.count("restart: ${AMX_RESTART_POLICY:-unless-stopped}") == 3


def test_api_startup_validates_runtime_security_before_side_effects():
    main = read("apps/api/app/main.py")

    assert "from app.core.runtime_security import validate_runtime_security_settings" in main
    assert "validate_runtime_security_settings()" in main
    assert main.index("validate_runtime_security_settings()") < main.index("await create_missing_tables()")


def test_worker_image_uses_single_runtime_worker_source():
    dockerfile = read("apps/worker/Dockerfile")

    assert "COPY apps/api/app ./app" in dockerfile
    assert "COPY apps/worker/app" not in dockerfile
    assert not (REPO_ROOT / "apps/worker/app/workers/queue.py").exists()


def test_production_deploy_runs_runtime_security_preflight_before_compose():
    deploy = read("infra/deploy/deploy-oci.sh")

    validator_call = "bash infra/deploy/validate-runtime-security.sh"
    assert validator_call in deploy
    assert '--environment "$ENVIRONMENT"' in deploy
    assert '--env-file "$ENV_FILE"' in deploy
    assert deploy.index(validator_call) < deploy.index("COMPOSE_COMMAND=(docker compose")
    assert "validator_args=(" in deploy
    assert "--verify-running" in deploy
    assert '--compose-file "$COMPOSE_FILE"' in deploy
    assert '--compose-project-name "$COMPOSE_PROJECT_NAME_OVERRIDE"' in deploy


def test_deployment_evidence_rechecks_runtime_security_contract():
    evidence = read("infra/deploy/deployment-evidence.sh")

    assert (
        'bash infra/deploy/validate-runtime-security.sh --environment production '
        '--verify-running --compose-file "$COMPOSE_FILE"'
    ) in evidence


def test_ci_exercises_production_runtime_security_preflight():
    workflow = read(".github/workflows/ci.yml")

    assert "Validate production runtime security preflight" in workflow
    assert "chmod 600 .env" in workflow
    assert "bash infra/deploy/validate-runtime-security.sh --environment production" in workflow


def test_ci_replaces_placeholder_jwt_secret_before_production_preflight():
    workflow = read(".github/workflows/ci.yml")

    assert "JWT_SECRET_KEY=ci-production-jwt-secret-at-least-32-bytes" in workflow
    assert workflow.index("JWT_SECRET_KEY=ci-production-jwt-secret-at-least-32-bytes") < workflow.index(
        "bash infra/deploy/validate-runtime-security.sh --environment production"
    )


def test_ci_replaces_placeholder_bootstrap_admin_password_before_production_preflight():
    workflow = read(".github/workflows/ci.yml")

    assert "BOOTSTRAP_ADMIN_PASSWORD=ci-bootstrap-admin-password" in workflow
    assert workflow.index("BOOTSTRAP_ADMIN_PASSWORD=ci-bootstrap-admin-password") < workflow.index(
        "bash infra/deploy/validate-runtime-security.sh --environment production"
    )


def test_ci_replaces_placeholder_database_password_before_production_preflight():
    workflow = read(".github/workflows/ci.yml")

    assert "POSTGRES_PASSWORD=ci-postgres-password-at-least-32-bytes" in workflow
    assert "ci-postgres-password-at-least-32-bytes@postgres:5432" in workflow
    assert workflow.index("POSTGRES_PASSWORD=ci-postgres-password-at-least-32-bytes") < workflow.index(
        "bash infra/deploy/validate-runtime-security.sh --environment production"
    )


def test_runtime_security_validator_rejects_public_binds_and_permissive_env():
    validator = read("infra/deploy/validate-runtime-security.sh")

    for variable in (
        "POSTGRES_BIND_ADDRESS",
        "REDIS_BIND_ADDRESS",
        "API_BIND_ADDRESS",
        "WEB_BIND_ADDRESS",
    ):
        assert variable in validator

    assert "Production bind address must be loopback" in validator
    assert "Production .env must not be readable or writable by group or other users" in validator
    assert "Running service port is not loopback-only" in validator
    assert 'compose_command=(docker compose --env-file "$ENV_FILE")' in validator
    assert 'compose_command+=(-p "$COMPOSE_PROJECT_NAME_OVERRIDE")' in validator
    assert 'bindings="$("${compose_command[@]}" port "$service" "$container_port")"' in validator
    assert '[[ "$ENVIRONMENT" != "production" ]]' in validator


def test_runtime_security_validator_rejects_placeholder_jwt_secret():
    validator = read("infra/deploy/validate-runtime-security.sh")

    assert "JWT_SECRET_KEY" in validator
    assert "your-super-secret-jwt-key-change-in-production" in validator
    assert "Production JWT_SECRET_KEY must be a real non-placeholder secret" in validator


def test_runtime_security_validator_rejects_placeholder_bootstrap_admin_password():
    validator = read("infra/deploy/validate-runtime-security.sh")

    assert "BOOTSTRAP_ADMIN_EMAIL" in validator
    assert "BOOTSTRAP_ADMIN_PASSWORD" in validator
    assert "change-me-in-production" in validator
    assert "Production BOOTSTRAP_ADMIN_PASSWORD must be a real non-placeholder password" in validator


def test_runtime_security_validator_rejects_default_database_passwords():
    validator = read("infra/deploy/validate-runtime-security.sh")

    assert "POSTGRES_PASSWORD" in validator
    assert "DATABASE_URL" in validator
    assert "consultant123" in validator
    assert "Production database credentials must not use example passwords" in validator
