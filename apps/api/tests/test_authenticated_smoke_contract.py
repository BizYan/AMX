"""Contract tests for the real API authenticated smoke script."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SMOKE_SCRIPT = REPO_ROOT / "infra" / "deploy" / "authenticated-smoke.sh"


def read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _bash_executable() -> str | None:
    bash = shutil.which("bash")
    if bash and "windows\\system32\\bash.exe" not in bash.lower():
        return bash
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        return str(git_bash)
    return bash


def _write_python3_shim(bin_dir: Path) -> None:
    python3 = bin_dir / "python3"
    python3.write_text(
        f"""#!/usr/bin/env bash
exec "{Path(sys.executable).as_posix()}" "$@"
""",
        encoding="utf-8",
    )
    python3.chmod(0o755)


def _bash_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    rest = resolved.as_posix().split(":", 1)[1] if ":" in resolved.as_posix() else resolved.as_posix()
    if drive:
        return f"/{drive}{rest}"
    return resolved.as_posix()


def _write_fake_curl(bin_dir: Path, log_path: Path, *, scenario: str = "success") -> None:
    curl = bin_dir / "curl"
    curl.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
url="${{@:$#}}"
printf '%s\\n' "$url" >> "{_bash_path(log_path)}"
case "$url" in
  */health)
    printf '{{"status":"healthy","version":"test"}}'
    ;;
  */api/v1/identity/auth/login)
    if [[ "{scenario}" == "bad-login" ]]; then
      printf '{{"detail":"invalid credentials"}}'
    else
      printf '{{"access_token":"real-smoke-token","token_type":"bearer"}}'
    fi
    ;;
  */api/v1/identity/auth/me)
    printf '{{"id":"00000000-0000-0000-0000-000000000001","email":"admin@example.com"}}'
    ;;
  */api/v1/projects*)
    printf '{{"items":[],"total":0,"page":1,"page_size":5,"has_more":false}}'
    ;;
  */api/v1/documents*)
    printf '{{"items":[],"total":0,"page":1,"page_size":5,"has_more":false}}'
    ;;
  */api/v1/providers/readiness)
    if [[ "{scenario}" == "sandbox-provider" ]]; then
      printf '{{"production_ready":false,"live_providers":0,"sandbox_providers":1,"mock_providers":0,"missing_required_types":["llm"],"items":[{{"readiness":"sandbox","name":"Sandbox LLM"}}]}}'
    else
      printf '{{"production_ready":true,"live_providers":3,"sandbox_providers":0,"mock_providers":0,"missing_required_types":[],"items":[{{"readiness":"live","name":"Live LLM"}}]}}'
    fi
    ;;
  */api/v1/ops/quota)
    printf '{{"used":1,"limit":1000,"resetAt":null}}'
    ;;
  */api/v1/ops/capabilities/readiness)
    if [[ "{scenario}" == "placeholder-capability" ]]; then
      printf '{{"production_ready":true,"overall_status":"ready","overall_score":90,"capabilities":[{{"key":"provider","status":"ready","evidence":{{"mode":"placeholder"}}}}]}}'
    else
      printf '{{"production_ready":true,"overall_status":"ready","overall_score":90,"capabilities":[{{"key":"provider","status":"ready","evidence":{{"live_provider_count":1}}}}]}}'
    fi
    ;;
  */api/v1/ops/capabilities/commissioning)
    printf '{{"production_usable":true,"overall_status":"ready","overall_score":90,"executed":false,"checks":[]}}'
    ;;
  *)
    printf '{{"error":"unexpected url","url":"%s"}}' "$url"
    exit 22
    ;;
esac
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)


def _run_smoke(tmp_path: Path, env_text: str, *, scenario: str = "success") -> subprocess.CompletedProcess[str]:
    bash = _bash_executable()
    if bash is None:
        pytest.skip("bash is required for shell smoke contract tests")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "curl-urls.log"
    _write_python3_shim(bin_dir)
    _write_fake_curl(bin_dir, log_path, scenario=scenario)
    env_file = tmp_path / ".env"
    env_file.write_text(env_text, encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{_bash_path(bin_dir)}:{env['PATH']}"
    env["CURL_BIN"] = _bash_path(bin_dir / "curl")
    return subprocess.run(
        [
            bash,
            str(SMOKE_SCRIPT),
            "--base-url",
            "https://amx.example.test",
            "--env-file",
            str(env_file),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_authenticated_smoke_covers_real_api_release_endpoints() -> None:
    script = read("infra/deploy/authenticated-smoke.sh")

    assert "setupApiMocks" not in script
    assert "/health" in script
    assert "/api/v1/identity/auth/login" in script
    assert "/api/v1/identity/auth/me" in script
    assert "/api/v1/projects?page=1&page_size=5" in script
    assert "/api/v1/documents?page=1&page_size=5" in script
    assert "/api/v1/providers/readiness" in script
    assert "/api/v1/ops/quota" in script
    assert "/api/v1/ops/capabilities/readiness" in script
    assert "/api/v1/ops/capabilities/commissioning" in script
    assert "assert_provider_readiness" in script
    assert "assert_capability_readiness" in script


def test_real_api_smoke_requires_real_credentials_without_fake_pass() -> None:
    script = read("infra/deploy/authenticated-smoke.sh")

    assert "BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD are required" in script
    assert "login did not return an access token" in script
    assert "mock-jwt-token" not in script
    assert "test_api_key" not in script


def test_release_docs_require_real_api_smoke_separate_from_mock_e2e() -> None:
    verification = read("docs/runbooks/development-verification-standard.md")
    release = read("docs/runbooks/release-management.md")

    assert "Real API smoke" in verification
    assert "deterministic mock E2E is not production-readiness evidence" in verification
    assert "bash infra/deploy/authenticated-smoke.sh" in verification
    assert "Real API smoke evidence is mandatory" in release


def test_authenticated_smoke_fails_when_credentials_are_missing(tmp_path: Path) -> None:
    result = _run_smoke(tmp_path, "BOOTSTRAP_ADMIN_EMAIL=\n")

    assert result.returncode == 1
    assert "BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD are required" in result.stderr


def test_authenticated_smoke_fails_clearly_when_login_returns_no_token(tmp_path: Path) -> None:
    result = _run_smoke(
        tmp_path,
        "BOOTSTRAP_ADMIN_EMAIL=admin@example.com\nBOOTSTRAP_ADMIN_PASSWORD=wrong-password\n",
        scenario="bad-login",
    )

    assert result.returncode == 1
    assert "login did not return an access token" in result.stderr


def test_authenticated_smoke_rejects_sandbox_provider_readiness(tmp_path: Path) -> None:
    result = _run_smoke(
        tmp_path,
        "BOOTSTRAP_ADMIN_EMAIL=admin@example.com\nBOOTSTRAP_ADMIN_PASSWORD=correct-password\n",
        scenario="sandbox-provider",
    )

    assert result.returncode == 1
    assert "provider readiness is not production-ready" in result.stderr
    assert "sandbox/mock/test provider evidence cannot satisfy real API smoke" in result.stderr


def test_authenticated_smoke_rejects_placeholder_capability_evidence(tmp_path: Path) -> None:
    result = _run_smoke(
        tmp_path,
        "BOOTSTRAP_ADMIN_EMAIL=admin@example.com\nBOOTSTRAP_ADMIN_PASSWORD=correct-password\n",
        scenario="placeholder-capability",
    )

    assert result.returncode == 1
    assert "capability readiness contains placeholder-only evidence" in result.stderr


def test_authenticated_smoke_succeeds_against_real_api_contract(tmp_path: Path) -> None:
    result = _run_smoke(
        tmp_path,
        "BOOTSTRAP_ADMIN_EMAIL=admin@example.com\nBOOTSTRAP_ADMIN_PASSWORD=correct-password\n",
    )

    assert result.returncode == 0, result.stderr
    assert "all authenticated production checks passed" in result.stdout
    urls = (tmp_path / "curl-urls.log").read_text(encoding="utf-8").splitlines()
    assert urls == [
        "https://amx.example.test/health",
        "https://amx.example.test/api/v1/identity/auth/login",
        "https://amx.example.test/api/v1/identity/auth/me",
        "https://amx.example.test/api/v1/projects?page=1&page_size=5",
        "https://amx.example.test/api/v1/documents?page=1&page_size=5",
        "https://amx.example.test/api/v1/providers/readiness",
        "https://amx.example.test/api/v1/ops/quota",
        "https://amx.example.test/api/v1/ops/capabilities/readiness",
        "https://amx.example.test/api/v1/ops/capabilities/commissioning",
    ]
