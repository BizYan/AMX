"""Provider production readiness summary tests."""

from types import SimpleNamespace
from uuid import uuid4

from app.domains.providers.readiness import build_provider_readiness_summary


def make_provider(name, provider_type, status="active", config=None):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        provider_type=provider_type,
        status=status,
        config_json=config if config is not None else {},
    )


def test_provider_readiness_summary_flags_live_sandbox_and_missing_core_types(monkeypatch):
    monkeypatch.setenv("AMX_TEST_LLM_API_KEY", "live-secret")
    tenant_id = uuid4()
    providers = [
        make_provider(
            "MiniMax Live",
            "llm",
            config={"credential_ref": "env:AMX_TEST_LLM_API_KEY", "base_url": "https://api.example.test"},
        ),
        make_provider(
            "GitNexus Sandbox",
            "gitnexus",
            config={"service_key": "mock", "mode": "sandbox"},
        ),
        make_provider(
            "Graphify Missing Credential",
            "graphify",
            config={"base_url": "https://graphify.example.test"},
        ),
    ]

    summary = build_provider_readiness_summary(
        tenant_id=tenant_id,
        providers=providers,
    )

    assert summary.tenant_id == tenant_id
    assert summary.total_providers == 3
    assert summary.live_providers == 1
    assert summary.sandbox_providers == 1
    assert summary.unconfigured_providers == 1
    assert summary.production_ready is False
    assert "gitnexus" in summary.missing_required_types
    assert "graphify" in summary.missing_required_types
    assert summary.required_types[0].provider_type == "llm"
    assert summary.required_types[0].status == "ready"
    assert any(item.provider_type == "gitnexus" and item.readiness == "sandbox" for item in summary.items)
    assert any("GitNexus Sandbox" in action for action in summary.recommended_actions)


def test_provider_readiness_distinguishes_live_mock_degraded_and_failed_states(monkeypatch):
    monkeypatch.setenv("AMX_TEST_LLM_API_KEY", "prod-secret-123456")
    monkeypatch.setenv("AMX_TEST_MOCK_LLM_API_KEY", "sk-test-123456")
    monkeypatch.setenv("AMX_TEST_GRAPHIFY_API_KEY", "prod-graphify-secret")
    monkeypatch.setenv("AMX_TEST_GITNEXUS_API_KEY", "prod-gitnexus-secret")
    tenant_id = uuid4()
    providers = [
        make_provider("Live LLM", "llm", config={"credential_ref": "env:AMX_TEST_LLM_API_KEY"}),
        make_provider("Mock LLM", "llm", config={"credential_ref": "env:AMX_TEST_MOCK_LLM_API_KEY"}),
        make_provider(
            "Graphify Live",
            "graphify",
            config={"credential_ref": "env:AMX_TEST_GRAPHIFY_API_KEY", "health_status": "degraded"},
        ),
        make_provider(
            "GitNexus Live",
            "gitnexus",
            config={"credential_ref": "env:AMX_TEST_GITNEXUS_API_KEY", "last_test_status": "failed"},
        ),
    ]

    summary = build_provider_readiness_summary(
        tenant_id=tenant_id,
        providers=providers,
    )

    readiness_by_name = {item.name: item.readiness for item in summary.items}

    assert readiness_by_name["Live LLM"] == "live"
    assert readiness_by_name["Mock LLM"] == "mock"
    assert readiness_by_name["Graphify Live"] == "degraded"
    assert readiness_by_name["GitNexus Live"] == "failed"
    assert summary.live_providers == 1
    assert summary.mock_providers == 1
    assert summary.degraded_providers == 1
    assert summary.failed_providers == 1
    assert summary.production_ready is False
    assert set(summary.missing_required_types) == {"graphify", "gitnexus"}
