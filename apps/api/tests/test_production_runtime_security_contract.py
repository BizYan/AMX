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
