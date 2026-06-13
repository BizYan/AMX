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
