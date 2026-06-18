"""Production runtime network and deployment-security contract checks."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


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
    assert "concurrency:" in workflow
    assert "secrets.RELEASE_CANDIDATE_BOOTSTRAP_ADMIN_EMAIL" in workflow
    assert "secrets.RELEASE_CANDIDATE_BOOTSTRAP_ADMIN_PASSWORD" in workflow
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
    assert 'test "$(git rev-parse HEAD)" = "$CANDIDATE_SHA"' in workflow
    assert 'git merge-base --is-ancestor "$CANDIDATE_SHA" origin/main' in workflow
    assert 'PROJECT_NAME="amx_rc_${SHORT_SHA}"' in workflow
    assert 'CANDIDATE_ENV_FILE=$RUNNER_TEMP/.env.rc.${SHORT_SHA}' in workflow
    assert "test -f infra/docker-compose.candidate.yml" in workflow
    assert "test -f infra/deploy/validate-candidate-verification.sh" in workflow
    assert 'CREATE EXTENSION IF NOT EXISTS \\\\"uuid-ossp\\\\";' in workflow
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in workflow
    assert "CREATE TABLE IF NOT EXISTS projects (id uuid PRIMARY KEY);" in workflow
    assert "CREATE TABLE IF NOT EXISTS documents (id uuid PRIMARY KEY);" in workflow
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
    assert "down -v --remove-orphans" in workflow
    assert "remaining_containers" in workflow
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


def test_runtime_containers_receive_explicit_environment():
    compose = read("infra/docker-compose.yml")
    deploy = read("infra/deploy/deploy-oci.sh")

    assert compose.count("ENVIRONMENT: ${ENVIRONMENT:-development}") == 2
    assert "export ENVIRONMENT" in deploy
    assert deploy.index("export ENVIRONMENT") < deploy.index('docker compose -f "$COMPOSE_FILE" config')


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

    validator_call = 'bash infra/deploy/validate-runtime-security.sh --environment "$ENVIRONMENT"'
    assert validator_call in deploy
    assert deploy.index(validator_call) < deploy.index('docker compose -f "$COMPOSE_FILE" config')
    assert (
        'bash infra/deploy/validate-runtime-security.sh --environment "$ENVIRONMENT" '
        '--verify-running --compose-file "$COMPOSE_FILE"'
    ) in deploy


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
    assert 'docker compose -f "$COMPOSE_FILE" port "$service" "$container_port"' in validator
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
