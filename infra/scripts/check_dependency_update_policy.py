#!/usr/bin/env python3
"""Reject automated dependency changes that cross a major-version boundary."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from typing import Any


VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")
PYTHON_NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?")
LOWER_BOUND_RE = re.compile(r"(?:>=|==|~=|>)\s*(\d+(?:\.\d+){0,2})")
UPPER_BOUND_RE = re.compile(r"(<)\s*(\d+(?:\.\d+){0,2})")


def _major(version: str) -> int | None:
    match = VERSION_RE.search(version)
    return int(match.group(1)) if match else None


def _python_requirements(dependencies: list[str]) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for dependency in dependencies:
        match = PYTHON_NAME_RE.match(dependency)
        if match:
            requirements[match.group(1).lower().replace("_", "-")] = dependency
    return requirements


def _upper_bound(requirement: str) -> str | None:
    match = UPPER_BOUND_RE.search(requirement)
    return f"{match.group(1)}{match.group(2)}" if match else None


def _lower_bound(requirement: str) -> str | None:
    match = LOWER_BOUND_RE.search(requirement)
    return match.group(1) if match else None


def compare_python_dependencies(before: list[str], after: list[str]) -> list[str]:
    """Return violations caused by broadening a Python requirement across majors."""
    old_requirements = _python_requirements(before)
    new_requirements = _python_requirements(after)
    violations: list[str] = []

    for name, old_requirement in old_requirements.items():
        new_requirement = new_requirements.get(name)
        if not new_requirement or new_requirement == old_requirement:
            continue

        old_lower = _lower_bound(old_requirement)
        new_lower = _lower_bound(new_requirement)
        if old_lower and new_lower and _major(new_lower) > _major(old_lower):
            violations.append(
                f"{name} changes declared major version "
                f"from {_major(old_lower)} to {_major(new_lower)}"
            )

        old_upper = _upper_bound(old_requirement)
        new_upper = _upper_bound(new_requirement)
        if old_upper and not new_upper:
            violations.append(f"{name} removes its protected upper bound {old_upper}")
            continue
        if old_upper and new_upper and _major(new_upper) > _major(old_upper):
            violations.append(
                f"{name} broadens its allowed major-version boundary "
                f"from {old_upper} to {new_upper}"
            )

    return violations


def compare_npm_dependencies(
    before: dict[str, str],
    after: dict[str, str],
) -> list[str]:
    """Return violations caused by changing an npm dependency's declared major."""
    violations: list[str] = []
    for name, old_requirement in before.items():
        new_requirement = after.get(name)
        if not new_requirement or new_requirement == old_requirement:
            continue

        old_major = _major(old_requirement)
        new_major = _major(new_requirement)
        if old_major is not None and new_major is not None and new_major > old_major:
            violations.append(f"{name} changes major version from {old_major} to {new_major}")
    return violations


def _git_show(ref: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{ref}:{path}"])


def _npm_dependencies(manifest: dict[str, Any]) -> dict[str, str]:
    dependencies: dict[str, str] = {}
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        dependencies.update(manifest.get(section, {}))
    return dependencies


def evaluate_refs(base: str, head: str) -> list[str]:
    """Compare supported manifests between two Git refs."""
    violations: list[str] = []

    before_web = json.loads(_git_show(base, "apps/web/package.json"))
    after_web = json.loads(_git_show(head, "apps/web/package.json"))
    violations.extend(
        compare_npm_dependencies(
            _npm_dependencies(before_web),
            _npm_dependencies(after_web),
        )
    )

    before_api = tomllib.loads(_git_show(base, "apps/api/pyproject.toml").decode("utf-8"))
    after_api = tomllib.loads(_git_show(head, "apps/api/pyproject.toml").decode("utf-8"))
    violations.extend(
        compare_python_dependencies(
            before_api["project"]["dependencies"],
            after_api["project"]["dependencies"],
        )
    )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()

    violations = evaluate_refs(args.base, args.head)
    if violations:
        print("Automated dependency update crosses a protected major-version boundary:")
        for violation in violations:
            print(f"- {violation}")
        print("Use an explicit engineering PR with compatibility evidence for major upgrades.")
        return 1

    print("Automated dependency update stays within protected major-version boundaries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
