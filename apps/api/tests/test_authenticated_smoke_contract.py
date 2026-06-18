"""Contracts for the real API authenticated smoke path."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_authenticated_smoke_covers_real_api_release_endpoints():
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


def test_real_api_smoke_requires_real_credentials_without_fake_pass():
    script = read("infra/deploy/authenticated-smoke.sh")

    assert "BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD are required" in script
    assert "login returned an empty access token" in script
    assert "mock-jwt-token" not in script
    assert "test_api_key" not in script


def test_release_docs_require_real_api_smoke_separate_from_mock_e2e():
    verification = read("docs/runbooks/development-verification-standard.md")
    release = read("docs/runbooks/release-management.md")

    assert "Real API smoke" in verification
    assert "deterministic mock E2E is not production-readiness evidence" in verification
    assert "bash infra/deploy/authenticated-smoke.sh" in verification
    assert "Real API smoke evidence is mandatory" in release
