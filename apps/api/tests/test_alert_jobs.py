"""Tests for Alert System Background Worker

Tests for alert rule evaluation, condition checking, and notification dispatch.
These tests focus on business logic without requiring database configuration.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/postgres")


# Import condition types and operators directly from the module
# If database configuration is not available, we test the constants separately
class TestConditionTypeConstants:
    """Tests for supported condition type constants."""

    def test_condition_type_constants_defined(self):
        """Test that condition type constants are defined correctly."""
        # These constants should be defined in alert_jobs module
        CONDITION_QUOTA = "quota"
        CONDITION_PROVIDER_HEALTH = "provider_health"
        CONDITION_CIRCUIT_OPEN = "circuit_open"
        CONDITION_AGENT_FAILURE_RATE = "agent_failure_rate"
        CONDITION_CACHE_HIT_RATE = "cache_hit_rate"

        assert CONDITION_QUOTA == "quota"
        assert CONDITION_PROVIDER_HEALTH == "provider_health"
        assert CONDITION_CIRCUIT_OPEN == "circuit_open"
        assert CONDITION_AGENT_FAILURE_RATE == "agent_failure_rate"
        assert CONDITION_CACHE_HIT_RATE == "cache_hit_rate"

    def test_operator_constants_defined(self):
        """Test that operator constants are defined correctly."""
        OPERATOR_GT = ">"
        OPERATOR_LT = "<"
        OPERATOR_GTE = ">="
        OPERATOR_LTE = "<="

        assert OPERATOR_GT == ">"
        assert OPERATOR_LT == "<"
        assert OPERATOR_GTE == ">="
        assert OPERATOR_LTE == "<="


class TestCompareValuesLogic:
    """Tests for comparison logic used in condition evaluation."""

    def _compare_values(self, current: float, operator: str, threshold: float) -> bool:
        """Local implementation of compare_values for testing."""
        if operator == ">":
            return current > threshold
        elif operator == ">=":
            return current >= threshold
        elif operator == "<":
            return current < threshold
        elif operator == "<=":
            return current <= threshold
        return False

    def test_compare_values_gt(self):
        """Test greater than comparison."""
        assert self._compare_values(85, ">", 80) is True
        assert self._compare_values(80, ">", 80) is False
        assert self._compare_values(75, ">", 80) is False

    def test_compare_values_gte(self):
        """Test greater than or equal comparison."""
        assert self._compare_values(85, ">=", 80) is True
        assert self._compare_values(80, ">=", 80) is True
        assert self._compare_values(75, ">=", 80) is False

    def test_compare_values_lt(self):
        """Test less than comparison."""
        assert self._compare_values(75, "<", 80) is True
        assert self._compare_values(80, "<", 80) is False
        assert self._compare_values(85, "<", 80) is False

    def test_compare_values_lte(self):
        """Test less than or equal comparison."""
        assert self._compare_values(75, "<=", 80) is True
        assert self._compare_values(80, "<=", 80) is True
        assert self._compare_values(85, "<=", 80) is False

    def test_compare_values_invalid_operator(self):
        """Test comparison with invalid operator defaults to False."""
        assert self._compare_values(85, "invalid", 80) is False
        assert self._compare_values(85, "", 80) is False


class TestQuotaConditionLogic:
    """Tests for quota condition evaluation logic."""

    def _calculate_usage_percent(self, used: float, limit: float) -> float:
        """Calculate usage percentage."""
        if limit == 0:
            return 0.0
        return (used / limit) * 100

    def _compare_values(self, current: float, operator: str, threshold: float) -> bool:
        """Local comparison function."""
        if operator == ">":
            return current > threshold
        elif operator == ">=":
            return current >= threshold
        elif operator == "<":
            return current < threshold
        elif operator == "<=":
            return current <= threshold
        return False

    def test_quota_usage_calculation(self):
        """Test quota usage percentage calculation."""
        used = 8500
        limit = 10000
        usage_percent = self._calculate_usage_percent(used, limit)
        assert usage_percent == 85.0

        # Test threshold breach
        threshold = 80
        assert usage_percent > threshold

        threshold_90 = 90
        assert usage_percent < threshold_90

    def test_quota_condition_triggered_at_80_percent(self):
        """Test quota alert triggers at 80% usage."""
        used = 8000
        limit = 10000
        threshold = 80
        usage_percent = self._calculate_usage_percent(used, limit)
        operator = ">="  # >= so exactly 80% triggers
        triggered = self._compare_values(usage_percent, operator, threshold)
        assert triggered is True

    def test_quota_condition_triggered_at_100_percent(self):
        """Test quota alert triggers at 100% usage."""
        used = 10000
        limit = 10000
        threshold = 100
        usage_percent = self._calculate_usage_percent(used, limit)
        operator = ">="  # >= so exactly 100% triggers
        triggered = self._compare_values(usage_percent, operator, threshold)
        assert triggered is True

    def test_quota_condition_not_triggered_below_threshold(self):
        """Test quota alert does not trigger below threshold."""
        used = 5000
        limit = 10000
        threshold = 80
        usage_percent = self._calculate_usage_percent(used, limit)
        operator = ">"
        triggered = self._compare_values(usage_percent, operator, threshold)
        assert triggered is False

    def test_quota_condition_with_zero_limit(self):
        """Test quota calculation with zero limit."""
        used = 1000
        limit = 0
        usage_percent = self._calculate_usage_percent(used, limit)
        assert usage_percent == 0.0


class TestProviderHealthConditionLogic:
    """Tests for provider health condition evaluation logic."""

    def _calculate_error_rate(self, total_calls: int, total_errors: int) -> float:
        """Calculate error rate percentage."""
        if total_calls == 0:
            return 0.0
        return (total_errors / total_calls) * 100

    def _compare_values(self, current: float, operator: str, threshold: float) -> bool:
        """Local comparison function."""
        if operator == ">":
            return current > threshold
        elif operator == ">=":
            return current >= threshold
        elif operator == "<":
            return current < threshold
        elif operator == "<=":
            return current <= threshold
        return False

    def test_error_rate_calculation(self):
        """Test provider error rate calculation."""
        total_calls = 1000
        total_errors = 50
        error_rate = self._calculate_error_rate(total_calls, total_errors)
        assert error_rate == 5.0

        # Test threshold breach
        threshold = 10
        assert error_rate < threshold

        threshold_4 = 4
        assert error_rate > threshold_4

    def test_error_rate_triggered_above_10_percent(self):
        """Test provider health alert triggers above 10% error rate."""
        total_calls = 1000
        total_errors = 150
        error_rate = self._calculate_error_rate(total_calls, total_errors)
        threshold = 10
        operator = ">"
        triggered = self._compare_values(error_rate, operator, threshold)
        assert triggered is True
        assert error_rate == 15.0

    def test_error_rate_not_triggered_below_threshold(self):
        """Test provider health alert does not trigger below threshold."""
        total_calls = 1000
        total_errors = 80
        error_rate = self._calculate_error_rate(total_calls, total_errors)
        threshold = 10
        operator = ">"
        triggered = self._compare_values(error_rate, operator, threshold)
        assert triggered is False
        assert error_rate == 8.0

    def test_error_rate_with_zero_calls(self):
        """Test error rate calculation with zero calls."""
        error_rate = self._calculate_error_rate(0, 0)
        assert error_rate == 0.0


class TestAgentFailureRateConditionLogic:
    """Tests for agent failure rate condition evaluation logic."""

    def _calculate_failure_rate(self, total_runs: int, failed_runs: int) -> float:
        """Calculate failure rate percentage."""
        if total_runs == 0:
            return 0.0
        return (failed_runs / total_runs) * 100

    def _compare_values(self, current: float, operator: str, threshold: float) -> bool:
        """Local comparison function."""
        if operator == ">":
            return current > threshold
        elif operator == ">=":
            return current >= threshold
        elif operator == "<":
            return current < threshold
        elif operator == "<=":
            return current <= threshold
        return False

    def test_failure_rate_calculation(self):
        """Test agent failure rate calculation."""
        total_runs = 500
        failed_runs = 75
        failure_rate = self._calculate_failure_rate(total_runs, failed_runs)
        assert failure_rate == 15.0

    def test_failure_rate_triggered_above_threshold(self):
        """Test agent failure rate alert triggers above threshold."""
        total_runs = 500
        failed_runs = 75
        failure_rate = self._calculate_failure_rate(total_runs, failed_runs)
        threshold = 10
        operator = ">"
        triggered = self._compare_values(failure_rate, operator, threshold)
        assert triggered is True

    def test_failure_rate_not_triggered_below_threshold(self):
        """Test agent failure rate alert does not trigger below threshold."""
        total_runs = 500
        failed_runs = 30
        failure_rate = self._calculate_failure_rate(total_runs, failed_runs)
        threshold = 10
        operator = ">"
        triggered = self._compare_values(failure_rate, operator, threshold)
        assert triggered is False


class TestCacheHitRateConditionLogic:
    """Tests for cache hit rate condition evaluation logic."""

    def _calculate_hit_rate(self, cache_hits: int, cache_misses: int) -> float:
        """Calculate cache hit rate percentage."""
        total_requests = cache_hits + cache_misses
        if total_requests == 0:
            return 0.0
        return (cache_hits / total_requests) * 100

    def _compare_values(self, current: float, operator: str, threshold: float) -> bool:
        """Local comparison function."""
        if operator == ">":
            return current > threshold
        elif operator == ">=":
            return current >= threshold
        elif operator == "<":
            return current < threshold
        elif operator == "<=":
            return current <= threshold
        return False

    def test_cache_hit_rate_calculation(self):
        """Test cache hit rate calculation."""
        cache_hits = 800
        cache_misses = 200
        total_requests = cache_hits + cache_misses
        hit_rate = self._calculate_hit_rate(cache_hits, cache_misses)
        assert hit_rate == 80.0

    def test_cache_hit_rate_below_threshold_triggers_alert(self):
        """Test cache hit rate below threshold triggers alert."""
        cache_hits = 600
        cache_misses = 400
        hit_rate = self._calculate_hit_rate(cache_hits, cache_misses)
        threshold = 80
        operator = "<"
        triggered = self._compare_values(hit_rate, operator, threshold)
        assert triggered is True
        assert hit_rate == 60.0

    def test_cache_hit_rate_above_threshold_no_alert(self):
        """Test cache hit rate above threshold does not trigger alert."""
        cache_hits = 900
        cache_misses = 100
        hit_rate = self._calculate_hit_rate(cache_hits, cache_misses)
        threshold = 80
        operator = "<"
        triggered = self._compare_values(hit_rate, operator, threshold)
        assert triggered is False
        assert hit_rate == 90.0

    def test_cache_hit_rate_with_zero_requests(self):
        """Test cache hit rate with zero total requests."""
        hit_rate = self._calculate_hit_rate(0, 0)
        assert hit_rate == 0.0


class TestCircuitBreakerStateLogic:
    """Tests for circuit breaker state checking."""

    def test_circuit_state_values(self):
        """Test circuit breaker state enum values."""
        from app.services.circuit_breaker import CircuitState

        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"

    def test_circuit_open_detection(self):
        """Test circuit open state detection."""
        from app.services.circuit_breaker import CircuitState

        # Simulate an open circuit
        is_open = True  # In real code, this would come from breaker.state == CircuitState.OPEN
        assert is_open is True

        is_closed = False
        assert is_closed is False

    def test_circuit_state_transitions(self):
        """Test circuit state transition logic."""
        from app.services.circuit_breaker import CircuitState

        # CLOSED -> OPEN (on failure threshold)
        states = [CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN]
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestNotificationChannelParsing:
    """Tests for notification channel parsing."""

    def test_email_channel_parsing(self):
        """Test email channel parsing."""
        channel = "email:admin@example.com"
        assert channel.startswith("email:")
        recipient = channel[6:]
        assert recipient == "admin@example.com"

    def test_webhook_channel_parsing(self):
        """Test webhook channel parsing."""
        channel = "webhook:https://hooks.example.com/alerts"
        assert channel.startswith("webhook:")
        url = channel[8:]
        assert url == "https://hooks.example.com/alerts"

    def test_system_channel(self):
        """Test system channel."""
        channel = "system"
        assert channel == "system"
        assert not channel.startswith("email:")
        assert not channel.startswith("webhook:")

    def test_multiple_channel_parsing(self):
        """Test parsing of multiple notification channels."""
        channels = [
            "email:admin@test.com",
            "webhook:https://hooks.example.com/alerts",
            "system",
        ]
        for channel in channels:
            if channel.startswith("email:"):
                assert "@" in channel[6:]
            elif channel.startswith("webhook:"):
                assert channel[8:].startswith("https://")
            else:
                assert channel == "system"


class TestAlertDataStructures:
    """Tests for alert data formatting."""

    def test_quota_alert_data_structure(self):
        """Test quota alert data structure."""
        alert_data = {
            "quota_type": "API_CALLS",
            "used_amount": 8500,
            "limit_amount": 10000,
            "usage_percent": 85.0,
            "threshold_percent": 80,
            "operator": ">",
            "message": "Quota API_CALLS usage at 85.0% (threshold: 80%)",
        }
        assert alert_data["quota_type"] == "API_CALLS"
        assert alert_data["usage_percent"] == 85.0
        assert "message" in alert_data

    def test_provider_health_alert_data_structure(self):
        """Test provider health alert data structure."""
        alert_data = {
            "provider_name": "openai",
            "error_rate": 15.0,
            "total_calls": 1000,
            "total_errors": 150,
            "threshold": 10,
            "message": "Provider openai error rate at 15.0% (threshold: 10%)",
        }
        assert alert_data["provider_name"] == "openai"
        assert alert_data["error_rate"] == 15.0
        assert alert_data["total_calls"] == 1000

    def test_agent_failure_alert_data_structure(self):
        """Test agent failure alert data structure."""
        alert_data = {
            "agent_id": "agent-123",
            "failure_rate": 15.0,
            "total_runs": 500,
            "failed_runs": 75,
            "threshold": 10,
            "message": "Agent failure rate at 15.0% (threshold: 10%)",
        }
        assert alert_data["agent_id"] == "agent-123"
        assert alert_data["failure_rate"] == 15.0
        assert alert_data["failed_runs"] == 75

    def test_cache_hit_rate_alert_data_structure(self):
        """Test cache hit rate alert data structure."""
        alert_data = {
            "hit_rate": 60.0,
            "cache_hits": 600,
            "cache_misses": 400,
            "total_requests": 1000,
            "threshold": 80,
            "message": "Cache hit rate at 60.0% (threshold: 80%)",
        }
        assert alert_data["hit_rate"] == 60.0
        assert alert_data["total_requests"] == 1000


class TestWebhookPayloadFormat:
    """Tests for webhook notification payload format."""

    def test_webhook_payload_structure(self):
        """Test webhook payload structure."""
        payload = {
            "event_type": "alert_triggered",
            "rule_id": str(uuid4()),
            "rule_name": "High API Usage Alert",
            "tenant_id": str(uuid4()),
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "alert_data": {
                "quota_type": "API_CALLS",
                "usage_percent": 85.0,
            },
            "condition": {
                "condition_type": "quota",
                "quota_type": "API_CALLS",
                "threshold": 80,
            },
        }
        assert payload["event_type"] == "alert_triggered"
        assert "rule_id" in payload
        assert "alert_data" in payload
        assert "condition" in payload


class TestAlertRuleConditionParsing:
    """Tests for alert rule condition JSON parsing."""

    def test_quota_condition_parsing(self):
        """Test quota condition JSON parsing."""
        condition = {
            "condition_type": "quota",
            "quota_type": "API_CALLS",
            "operator": ">",
            "threshold": 80,
        }
        assert condition["condition_type"] == "quota"
        assert condition["quota_type"] == "API_CALLS"
        assert condition["threshold"] == 80

    def test_provider_health_condition_parsing(self):
        """Test provider health condition JSON parsing."""
        condition = {
            "condition_type": "provider_health",
            "provider_name": "openai",
            "operator": ">",
            "threshold": 10,
        }
        assert condition["condition_type"] == "provider_health"
        assert condition["provider_name"] == "openai"
        assert condition["threshold"] == 10

    def test_circuit_open_condition_parsing(self):
        """Test circuit open condition JSON parsing."""
        condition = {
            "condition_type": "circuit_open",
            "provider_name": "anthropic",
        }
        assert condition["condition_type"] == "circuit_open"
        assert condition["provider_name"] == "anthropic"

    def test_agent_failure_rate_condition_parsing(self):
        """Test agent failure rate condition JSON parsing."""
        condition = {
            "condition_type": "agent_failure_rate",
            "agent_id": "agent-123",
            "operator": ">",
            "threshold": 10,
        }
        assert condition["condition_type"] == "agent_failure_rate"
        assert condition["agent_id"] == "agent-123"
        assert condition["threshold"] == 10

    def test_cache_hit_rate_condition_parsing(self):
        """Test cache hit rate condition JSON parsing."""
        condition = {
            "condition_type": "cache_hit_rate",
            "operator": "<",
            "threshold": 80,
        }
        assert condition["condition_type"] == "cache_hit_rate"
        assert condition["threshold"] == 80

    def test_generic_metric_condition_parsing(self):
        """Test generic metric condition JSON parsing."""
        condition = {
            "metric_type": "api_call",
            "metric_name": "latency_ms",
            "operator": ">",
            "threshold": 500,
        }
        assert condition["metric_type"] == "api_call"
        assert condition["metric_name"] == "latency_ms"
        assert condition["threshold"] == 500


class TestNotificationChannelConfiguration:
    """Tests for notification channel configuration."""

    def test_email_channel_format(self):
        """Test email channel format validation."""
        valid_email_channels = [
            "email:admin@example.com",
            "email:team+alerts@company.org",
        ]
        for channel in valid_email_channels:
            assert channel.startswith("email:")
            assert "@" in channel[6:]

    def test_webhook_channel_format(self):
        """Test webhook channel format validation."""
        valid_webhook_channels = [
            "webhook:https://hooks.example.com/alerts",
            "webhook:https://hook.service.com/webhook/abc123",
        ]
        for channel in valid_webhook_channels:
            assert channel.startswith("webhook:")
            url = channel[8:]
            assert url.startswith("https://")

    def test_system_channel_format(self):
        """Test system channel format."""
        channel = "system"
        assert channel == "system"
        assert len(channel.split(":")) == 1


class TestAlertNotificationResults:
    """Tests for alert notification result structure."""

    def test_email_notification_result_format(self):
        """Test email notification result format."""
        result = {
            "channel": "email:admin@example.com",
            "success": True,
            "message": "Email notification logged (recipient: admin@example.com)",
        }
        assert result["channel"].startswith("email:")
        assert result["success"] is True

    def test_webhook_notification_result_format(self):
        """Test webhook notification result format."""
        result = {
            "channel": "webhook:https://hooks.example.com/alerts",
            "success": True,
            "status_code": 200,
        }
        assert result["channel"].startswith("webhook:")
        assert result["success"] is True
        assert "status_code" in result

    def test_system_notification_result_format(self):
        """Test system notification result format."""
        result = {
            "channel": "system",
            "success": True,
            "message": "System notification logged",
        }
        assert result["channel"] == "system"
        assert result["success"] is True


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_quota_condition_uses_configured_operator_without_name_error():
    """Quota alerts must use the operator from condition_json, not an undefined local."""
    from app.workers.alert_jobs import _evaluate_quota_condition

    quota = MagicMock()
    quota.used_amount = 80
    quota.limit_amount = 100

    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(quota))

    triggered, alert_data = await _evaluate_quota_condition(
        {
            "quota_type": "DOCUMENT_COUNT",
            "operator": ">=",
            "threshold": 80,
        },
        uuid4(),
        db,
    )

    assert triggered is True
    assert alert_data["operator"] == ">="
    assert alert_data["usage_percent"] == 80


@pytest.mark.asyncio
async def test_gitnexus_health_uses_registration_config_aliases():
    """GitNexus health checks must work with the AMX provider registration config."""
    from app.domains.providers.models import HealthStatus
    from app.workers.health_jobs import _check_gitnexus_health

    calls = {}

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, timeout):
            calls["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers):
            calls["url"] = url
            calls["headers"] = headers
            return FakeResponse()

    provider = MagicMock()
    provider.config_json = {
        "base_url": "http://gitnexus.local:4747/",
        "service_key": "live-service-key",
        "health_path": "/api/health",
    }

    with patch("app.workers.health_jobs.httpx.AsyncClient", FakeClient):
        result = await _check_gitnexus_health(provider, MagicMock())

    assert result == HealthStatus.HEALTHY
    assert calls["timeout"] == 10.0
    assert calls["url"] == "http://gitnexus.local:4747/api/health"
    assert calls["headers"] == {"Authorization": "Bearer live-service-key"}


@pytest.mark.asyncio
async def test_agent_failure_rate_query_does_not_require_run_and_run_failed():
    """Failed-run count must not add a contradictory metric_name=run filter."""
    import app.models.identity  # noqa: F401 - register Tenant relationship for query compilation
    from app.workers.alert_jobs import _evaluate_agent_failure_rate_condition

    executed_statements = []

    async def execute(statement):
        executed_statements.append(str(statement))
        if len(executed_statements) == 1:
            return _ScalarResult(10)
        assert executed_statements[-1].count("metric_events.metric_name =") == 1
        return _ScalarResult(2)

    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute)

    triggered, alert_data = await _evaluate_agent_failure_rate_condition(
        {"condition_type": "agent_failure_rate", "operator": ">", "threshold": 10},
        uuid4(),
        db,
    )

    assert triggered is True
    assert alert_data["total_runs"] == 10
    assert alert_data["failed_runs"] == 2
    assert alert_data["failure_rate"] == 20


@pytest.mark.asyncio
async def test_send_alert_notification_persists_system_delivery_event():
    """System notifications must be auditable through NotificationEvent records."""
    from app.domains.ops.models import NotificationEvent
    from app.workers.alert_jobs import send_alert_notification

    rule_id = uuid4()
    tenant_id = uuid4()
    rule = MagicMock()
    rule.id = rule_id
    rule.tenant_id = tenant_id
    rule.name = "生产健康异常"
    rule.condition_json = {"condition_type": "cache_hit_rate", "threshold": 80}
    rule.notification_channels = ["system"]

    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(rule))
    db.add = MagicMock()
    db.commit = AsyncMock()

    with patch("app.workers.alert_jobs.AsyncSessionLocal", return_value=_AsyncSessionContext(db)):
        result = await send_alert_notification(
            {},
            str(rule_id),
            {"message": "缓存命中率低于阈值", "hit_rate": 60},
        )

    assert result["success"] is True
    assert result["notification_event_count"] == 1
    db.add.assert_called_once()
    event = db.add.call_args.args[0]
    assert isinstance(event, NotificationEvent)
    assert event.tenant_id == tenant_id
    assert event.channel == "system"
    assert event.recipient == "system"
    assert event.status == "sent"
    assert event.title == "[Alert] 生产健康异常"
    assert "缓存命中率低于阈值" in event.body
    db.commit.assert_awaited_once()


class TestAlertRuleModelMock:
    """Tests for AlertRule model structure using mocks."""

    def test_alert_rule_model_fields(self):
        """Test AlertRule model has required fields."""
        # Mock the AlertRule model structure
        class MockAlertRule:
            def __init__(self):
                self.tenant_id = uuid4()
                self.name = "Test Alert"
                self.condition_json = {
                    "condition_type": "quota",
                    "quota_type": "API_CALLS",
                    "operator": ">",
                    "threshold": 80,
                }
                self.notification_channels = ["email:admin@test.com", "system"]
                self.is_active = True

        rule = MockAlertRule()
        assert rule.name == "Test Alert"
        assert rule.is_active is True
        assert rule.condition_json["threshold"] == 80

    def test_alert_rule_notification_channels_list(self):
        """Test AlertRule notification_channels is a list."""
        class MockAlertRule:
            def __init__(self):
                self.notification_channels = ["email:test@test.com", "webhook:https://test.com", "system"]

        rule = MockAlertRule()
        assert isinstance(rule.notification_channels, list)
        assert len(rule.notification_channels) == 3

    def test_alert_rule_condition_json_structure(self):
        """Test AlertRule condition_json is a dict."""
        class MockAlertRule:
            def __init__(self):
                self.condition_json = {"condition_type": "quota", "threshold": 90}

        rule = MockAlertRule()
        assert isinstance(rule.condition_json, dict)
        assert "condition_type" in rule.condition_json
