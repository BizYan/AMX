"""Regression checks for deterministic GitNexus production images."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_gitnexus_deployment_pins_cli_compatible_images():
    compose = (REPO_ROOT / "infra/gitnexus/docker-compose.yml").read_text(encoding="utf-8")
    env_example = (REPO_ROOT / "infra/gitnexus/env.example").read_text(encoding="utf-8")
    deploy_script = (REPO_ROOT / "infra/deploy/deploy-gitnexus.sh").read_text(encoding="utf-8")
    refresh_script = (REPO_ROOT / "infra/deploy/refresh-gitnexus.sh").read_text(encoding="utf-8")

    assert "ghcr.io/abhigyanpatwari/gitnexus:1.6.5" in compose
    assert "ghcr.io/abhigyanpatwari/gitnexus-web:1.6.5" in compose
    assert "ghcr.io/abhigyanpatwari/gitnexus:latest" not in compose
    assert "ghcr.io/abhigyanpatwari/gitnexus-web:latest" not in compose
    assert "GITNEXUS_SERVER_IMAGE=ghcr.io/abhigyanpatwari/gitnexus:1.6.5" in env_example
    assert "GITNEXUS_WEB_IMAGE=ghcr.io/abhigyanpatwari/gitnexus-web:1.6.5" in env_example
    assert "GITNEXUS_SERVER_IMAGE=\"${GITNEXUS_SERVER_IMAGE:-ghcr.io/abhigyanpatwari/gitnexus:1.6.5}\"" in deploy_script
    assert "GITNEXUS_WEB_IMAGE=\"${GITNEXUS_WEB_IMAGE:-ghcr.io/abhigyanpatwari/gitnexus-web:1.6.5}\"" in deploy_script
    assert 'server_image_override="${GITNEXUS_SERVER_IMAGE:-}"' in refresh_script
    assert 'export GITNEXUS_SERVER_IMAGE="$server_image_override"' in refresh_script
    assert 'gitnexus analyze "$repo_path" --index-only --force' in refresh_script


def test_gitnexus_deployment_migrates_existing_clone_to_public_amx():
    deploy_script = (REPO_ROOT / "infra/deploy/deploy-gitnexus.sh").read_text(encoding="utf-8")
    refresh_script = (REPO_ROOT / "infra/deploy/refresh-gitnexus.sh").read_text(encoding="utf-8")
    env_example = (REPO_ROOT / "infra/gitnexus/env.example").read_text(encoding="utf-8")

    assert 'SOURCE_REPO="${SOURCE_REPO:-/home/ubuntu/amx/production/AMX}"' in deploy_script
    assert 'WORKSPACE_REPO_NAME="${WORKSPACE_REPO_NAME:-AMX}"' in deploy_script
    assert 'git -C "$WORKSPACE_REPO_DIR" remote set-url origin "$REPOSITORY_URL"' in deploy_script
    assert 'gitnexus remove "$legacy_repo_path"' in refresh_script
    assert "GITNEXUS_REPOSITORY_PATH=/workspace/AMX" in env_example


def test_deployment_evidence_requires_gitnexus_indexed_commit_to_match_release():
    evidence_script = (REPO_ROOT / "infra/deploy/deployment-evidence.sh").read_text(encoding="utf-8")

    assert 'GITNEXUS_REPOSITORY_PATH="${GITNEXUS_REPOSITORY_PATH:-/workspace/AMX}"' in evidence_script
    assert 'exec -T gitnexus-server git -C "$GITNEXUS_REPOSITORY_PATH" rev-parse HEAD' in evidence_script
    assert 'if [[ "$gitnexus_repo_sha" != "$DEPLOYED_SHA" ]]' in evidence_script
    assert '"gitnexus_indexed_sha": os.environ["GITNEXUS_REPO_SHA"]' in evidence_script


def test_public_amx_runtime_migration_preserves_legacy_compatibility_link():
    migration_script = (REPO_ROOT / "infra/deploy/migrate-public-amx-runtime.sh").read_text(
        encoding="utf-8"
    )

    assert 'CANONICAL_PATH="${CANONICAL_PATH:-/home/ubuntu/amx/production/AMX}"' in migration_script
    assert 'LEGACY_PATH="${LEGACY_PATH:-/home/ubuntu/amx/production/ConsultantAIP}"' in migration_script
    assert 'LEGACY_ROOT_PATH="${LEGACY_ROOT_PATH:-/home/ubuntu/ConsultantAIP}"' in migration_script
    assert 'REPOSITORY_URL="${REPOSITORY_URL:-https://github.com/BizYan/AMX.git}"' in migration_script
    assert 'mv "$legacy_real_path" "$CANONICAL_PATH"' in migration_script
    assert 'ln -s "$CANONICAL_PATH" "$LEGACY_PATH"' in migration_script
    assert 'ln -s "$CANONICAL_PATH" "$LEGACY_ROOT_PATH"' in migration_script
    assert 'git -C "$CANONICAL_PATH" remote set-url origin "$REPOSITORY_URL"' in migration_script
    assert "Canonical and legacy paths both exist as real directories" in migration_script


def test_production_workflow_requires_canonical_public_amx_path():
    workflow = (REPO_ROOT / ".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    assert 'EXPECTED_PRODUCTION_PATH: /home/ubuntu/amx/production/AMX' in workflow
    assert 'if [ "$AMX_PRODUCTION_PATH" != "$EXPECTED_PRODUCTION_PATH" ]; then' in workflow
