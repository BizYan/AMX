"""Provider credential boundary regression tests."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.providers.capability import provider_secret_value
from app.domains.providers.credential_boundary import (
    REDACTED_SECRET,
    provider_runtime_config,
    sanitize_error_message,
    validate_provider_config_boundary,
)
from app.domains.providers.models import Provider, ProviderStatus, ProviderType, RunStatus
from app.domains.providers.registry import ProviderRegistry
from app.domains.providers.schemas import ProviderCreate, ProviderResponse, ProviderRunResponse, ProviderVersionCreate


def _provider(config: dict) -> Provider:
    provider = Provider()
    provider.id = uuid4()
    provider.tenant_id = uuid4()
    provider.name = "Candidate LLM"
    provider.provider_type = ProviderType.LLM.value
    provider.status = ProviderStatus.ACTIVE.value
    provider.config_json = config
    provider.capabilities_json = None
    provider.current_version_id = None
    provider.created_at = provider.updated_at = datetime.now(timezone.utc)
    return provider


def test_provider_config_boundary_rejects_raw_credentials_in_create_and_versions():
    with pytest.raises(ValueError, match="api_key"):
        validate_provider_config_boundary({"base_url": "https://api.example.test", "api_key": "sk-live-secret"})

    with pytest.raises(ValidationError, match="service_key"):
        ProviderCreate(
            name="GitNexus",
            provider_type=ProviderType.GITNEXUS,
            config={"base_url": "https://gitnexus.example.test", "service_key": "live-service-key"},
        )

    with pytest.raises(ValidationError, match="access_token"):
        ProviderVersionCreate(
            version="2.0",
            config={"auth": {"access_token": "raw-token"}},
        )


def test_provider_responses_redact_legacy_raw_credentials():
    response = ProviderResponse.model_validate(
        _provider(
            {
                "base_url": "https://api.example.test",
                "api_key": "sk-live-secret",
                "nested": {"token": "nested-live-token"},
                "credential_ref": "env:AMX_CANDIDATE_LLM_API_KEY",
            }
        )
    )

    assert response.config_json["api_key"] == REDACTED_SECRET
    assert response.config_json["nested"]["token"] == REDACTED_SECRET
    assert response.config_json["credential_ref"] == "env:AMX_CANDIDATE_LLM_API_KEY"
    assert "sk-live-secret" not in str(response.model_dump())
    assert "nested-live-token" not in str(response.model_dump())


@pytest.mark.asyncio
async def test_provider_registry_sanitizes_persisted_run_errors():
    db = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock()
    registry = ProviderRegistry(db)
    provider_id = uuid4()

    run = await registry.record_run(
        tenant_id=uuid4(),
        provider_id=provider_id,
        version_id=None,
        capability_type="text_generation",
        status=RunStatus.FAILURE,
        error_message="upstream rejected Authorization: Bearer sk-live-secret and api_key=abc123",
    )

    assert REDACTED_SECRET in run.error_message
    assert "sk-live-secret" not in run.error_message
    assert "abc123" not in run.error_message


def test_provider_runtime_config_resolves_candidate_env_without_persisting_raw_secret(monkeypatch):
    monkeypatch.setenv("AMX_CANDIDATE_LLM_API_KEY", "candidate-runtime-secret")
    provider = _provider(
        {
            "base_url": "https://api.example.test",
            "model": "MiniMax-Text-01",
            "credential_ref": "env:AMX_CANDIDATE_LLM_API_KEY",
        }
    )

    assert provider_secret_value(provider) == "candidate-runtime-secret"
    runtime_config = provider_runtime_config(provider, credential_key="api_key")

    assert runtime_config["api_key"] == "candidate-runtime-secret"
    assert provider.config_json == {
        "base_url": "https://api.example.test",
        "model": "MiniMax-Text-01",
        "credential_ref": "env:AMX_CANDIDATE_LLM_API_KEY",
    }


def test_provider_runs_are_not_loaded_with_provider_readiness_queries():
    assert Provider.runs.property.lazy == "noload"


def test_error_redaction_covers_api_key_bearer_and_response_models():
    raw = "HTTP 401 for api_key=abc123 with Authorization: Bearer sk-live-secret"
    sanitized = sanitize_error_message(raw)

    assert "abc123" not in sanitized
    assert "sk-live-secret" not in sanitized
    assert sanitized.count(REDACTED_SECRET) >= 2

    response = ProviderRunResponse.model_validate(
        SimpleNamespace(
            id=uuid4(),
            tenant_id=uuid4(),
            provider_id=uuid4(),
            version_id=None,
            capability_type="text_generation",
            input_tokens=None,
            output_tokens=None,
            latency_ms=12,
            status="failure",
            error_message=raw,
            created_at=datetime.now(timezone.utc),
        )
    )

    assert "abc123" not in response.error_message
    assert "sk-live-secret" not in response.error_message
