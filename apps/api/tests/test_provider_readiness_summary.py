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


def test_provider_readiness_summary_flags_live_sandbox_and_missing_core_types():
    tenant_id = uuid4()
    providers = [
        make_provider(
            "MiniMax Live",
            "llm",
            config={"api_key": "live-secret", "base_url": "https://api.example.test"},
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
