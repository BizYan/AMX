"""Dependency automation and governance contract checks."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_dependabot_excludes_major_version_updates():
    config = read(".github/dependabot.yml")

    assert config.count('update-types: ["minor", "patch"]') == 2
    assert config.count("- version-update:semver-major") == 2


def test_dependabot_governance_allows_only_dependency_files():
    workflow = read(".github/workflows/collaboration-governance.yml")

    assert "dependabot[bot]" in workflow
    for path in (
        "apps/web/package.json",
        "apps/web/pnpm-lock.yaml",
        "apps/api/pyproject.toml",
        "apps/api/uv.lock",
    ):
        assert path in workflow

    assert "Dependabot PR changed a non-dependency file" in workflow
