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
