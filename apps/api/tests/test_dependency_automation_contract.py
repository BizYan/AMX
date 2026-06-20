"""Dependency automation and governance contract checks."""

import importlib.util
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_SCRIPT = REPO_ROOT / "infra/scripts/check_dependency_update_policy.py"


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
    assert 'delta_base="$(git merge-base "$base_sha" "$head_sha")"' in workflow
    assert 'git diff --name-only "$delta_base" "$head_sha"' in workflow
    assert '--base "$delta_base"' in workflow
    assert "check_dependency_update_policy.py" in workflow


def load_policy_module():
    spec = importlib.util.spec_from_file_location("dependency_update_policy", POLICY_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_python_dependency_policy_rejects_major_upper_bound_broadening():
    policy = load_policy_module()

    violations = policy.compare_python_dependencies(
        ['bcrypt>=4.0,<4.1'],
        ['bcrypt>=4.0,<5.1'],
    )

    assert violations == [
        "bcrypt broadens its allowed major-version boundary from <4.1 to <5.1"
    ]


def test_python_dependency_policy_allows_same_major_maintenance_range():
    policy = load_policy_module()

    assert policy.compare_python_dependencies(
        ['bcrypt>=4.0,<4.1'],
        ['bcrypt>=4.0,<4.4'],
    ) == []


def test_python_dependency_policy_rejects_major_floor_change():
    policy = load_policy_module()

    violations = policy.compare_python_dependencies(
        ['fastapi>=0.115.0'],
        ['fastapi>=1.0.0'],
    )

    assert violations == ["fastapi changes declared major version from 0 to 1"]


def test_python_dependency_policy_rejects_removing_upper_bound():
    policy = load_policy_module()

    violations = policy.compare_python_dependencies(
        ['bcrypt>=4.0,<4.1'],
        ['bcrypt>=4.0'],
    )

    assert violations == ["bcrypt removes its protected upper bound <4.1"]


def test_npm_dependency_policy_rejects_major_upgrade():
    policy = load_policy_module()

    violations = policy.compare_npm_dependencies(
        {"next": "^15.5.18"},
        {"next": "^16.0.1"},
    )

    assert violations == ["next changes major version from 15 to 16"]


def test_python_compatibility_bounds_are_explicit():
    manifest = read("apps/api/pyproject.toml")

    match = re.search(r'"bcrypt>=4\.0,<(?P<upper>\d+)\.\d+"', manifest)

    assert match
    assert match.group("upper") == "4"
