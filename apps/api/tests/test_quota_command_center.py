"""Quota production operations command center tests."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4


def evidence(**overrides):
    payload = {
        "tenant_id": uuid4(),
        "generated_at": datetime.now(timezone.utc),
        "api_used": 2400,
        "api_limit": 10000,
        "api_reset_at": datetime.now(timezone.utc),
        "total_requests": 2400,
        "successful_requests": 2380,
        "failed_requests": 20,
        "average_latency_ms": 210.0,
        "rate_limits": [
            {
                "endpoint": "/api/documents",
                "limit": 1000,
                "remaining": 800,
                "reset_at": datetime.now(timezone.utc),
            }
        ],
        "provider_risks": [],
        "open_breakers": [],
    }
    payload.update(overrides)
    return payload


def test_quota_command_center_blocks_critical_quota_and_open_breaker():
    from app.domains.ops.quota_command_center import QuotaCommandCenterService

    result = QuotaCommandCenterService.build_from_evidence(
        evidence(
            api_used=9600,
            failed_requests=180,
            open_breakers=["graphify-service-breaker"],
        )
    )

    assert result.release_gate.status == "blocked"
    assert result.release_gate.can_operate is False
    assert result.summary.api_usage_percent == 96.0
    assert result.summary.open_breaker_count == 1
    assert result.risk_items[0].severity == "critical"
    assert any(action.href == "/providers" for action in result.priority_actions)


def test_quota_command_center_requires_attention_for_degraded_evidence():
    from app.domains.ops.quota_command_center import QuotaCommandCenterService

    result = QuotaCommandCenterService.build_from_evidence(
        evidence(
            api_used=8300,
            failed_requests=150,
            provider_risks=[{"name": "OpenAI LLM", "status": "degraded", "detail": "High retry rate"}],
            rate_limits=[
                {
                    "endpoint": "/api/agent",
                    "limit": 100,
                    "remaining": 8,
                    "reset_at": datetime.now(timezone.utc),
                }
            ],
        )
    )

    assert result.release_gate.status == "attention"
    assert result.release_gate.can_operate is True
    assert result.summary.api_usage_percent == 83.0
    assert result.summary.failure_rate_percent > 5
    assert result.summary.risky_endpoint_count == 1
    assert result.summary.provider_risk_count == 1
    assert {item.code for item in result.risk_items} >= {
        "api_quota_attention",
        "failure_rate_attention",
        "rate_limit_attention",
        "provider_health_attention",
    }


def test_quota_command_center_passes_healthy_evidence():
    from app.domains.ops.quota_command_center import QuotaCommandCenterService

    result = QuotaCommandCenterService.build_from_evidence(evidence())

    assert result.release_gate.status == "passed"
    assert result.release_gate.can_operate is True
    assert result.risk_items == []
    assert result.priority_actions == []
    assert result.summary.api_remaining == 7600


def test_quota_command_center_does_not_use_future_reset_as_period_start():
    from app.domains.ops.quota_command_center import QuotaCommandCenterService

    now = datetime.now(timezone.utc)
    period_start = QuotaCommandCenterService.resolve_period_start(now + timedelta(days=10), now)

    assert period_start == now - timedelta(days=30)
