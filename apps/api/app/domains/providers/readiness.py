"""Provider production readiness aggregation."""

from collections.abc import Iterable
from uuid import UUID

from app.domains.providers.capability import (
    config_text,
    is_live_configured,
    provider_fake_configuration_kind,
)
from app.domains.providers.models import ProviderStatus
from app.domains.providers.schemas import (
    ProviderReadinessItem,
    ProviderReadinessSummary,
    ProviderRequiredTypeReadiness,
)


REQUIRED_PROVIDER_TYPES = [
    ("llm", "LLM generation"),
    ("graphify", "Graphify graph extraction"),
    ("gitnexus", "GitNexus code index"),
]


def _provider_id(provider) -> UUID:
    return provider.id


def _provider_type(provider) -> str:
    return str(getattr(provider, "provider_type", "") or "").lower()


def _provider_status(provider) -> str:
    return str(getattr(provider, "status", "") or "")


def _operational_status(provider) -> str:
    config = getattr(provider, "config_json", None) or {}
    return config_text(config, "last_test_status", "health_status", "connection_status").lower()


def _classify_provider(provider) -> tuple[str, str, str]:
    provider_type = _provider_type(provider)
    status = _provider_status(provider)
    operational_status = _operational_status(provider)

    if status != ProviderStatus.ACTIVE.value:
        return (
            "inactive",
            "Provider is not active.",
            "Enable the provider only after production credentials and checks are ready.",
        )

    fake_kind = provider_fake_configuration_kind(provider)
    if fake_kind == "sandbox":
        return (
            "sandbox",
            "Provider uses sandbox configuration.",
            f"Configure real production credentials and mode for {getattr(provider, 'name', 'Provider')}.",
        )
    if fake_kind == "mock":
        return (
            "mock",
            "Provider uses mock/test/demo/placeholder configuration.",
            f"Replace fake credentials and test configuration for {getattr(provider, 'name', 'Provider')}.",
        )

    if not is_live_configured(provider):
        return (
            "unconfigured",
            "Provider is missing live credentials or required production configuration.",
            f"Configure credential_ref/secret_ref and endpoint for {getattr(provider, 'name', 'Provider')}.",
        )

    if operational_status in {"failed", "failure", "down", "error"}:
        return (
            "failed",
            "Provider has live credentials but its latest check failed.",
            f"Fix the latest connection failure before using {getattr(provider, 'name', 'Provider')} as production-ready.",
        )
    if operational_status in {"degraded", "partial", "warning"}:
        return (
            "degraded",
            "Provider has live credentials but is degraded.",
            f"Resolve degraded health before treating {getattr(provider, 'name', 'Provider')} as fully production-ready.",
        )

    return (
        "live",
        f"{provider_type or 'provider'} has live production configuration.",
        "Keep scheduled production checks and audit evidence current.",
    )


def build_provider_readiness_summary(
    *,
    tenant_id: UUID,
    providers: Iterable,
) -> ProviderReadinessSummary:
    """Build tenant-level provider production readiness from provider rows."""
    provider_list = list(providers)
    items: list[ProviderReadinessItem] = []
    live_by_type: dict[str, int] = {}
    sandbox_by_type: dict[str, int] = {}
    mock_by_type: dict[str, int] = {}
    unconfigured_by_type: dict[str, int] = {}
    inactive_by_type: dict[str, int] = {}
    degraded_by_type: dict[str, int] = {}
    failed_by_type: dict[str, int] = {}

    for provider in provider_list:
        readiness, reason, recommended_action = _classify_provider(provider)
        provider_type = _provider_type(provider)
        if readiness == "live":
            live_by_type[provider_type] = live_by_type.get(provider_type, 0) + 1
        elif readiness == "sandbox":
            sandbox_by_type[provider_type] = sandbox_by_type.get(provider_type, 0) + 1
        elif readiness == "mock":
            mock_by_type[provider_type] = mock_by_type.get(provider_type, 0) + 1
        elif readiness == "unconfigured":
            unconfigured_by_type[provider_type] = unconfigured_by_type.get(provider_type, 0) + 1
        elif readiness == "degraded":
            degraded_by_type[provider_type] = degraded_by_type.get(provider_type, 0) + 1
        elif readiness == "failed":
            failed_by_type[provider_type] = failed_by_type.get(provider_type, 0) + 1
        else:
            inactive_by_type[provider_type] = inactive_by_type.get(provider_type, 0) + 1

        items.append(
            ProviderReadinessItem(
                provider_id=_provider_id(provider),
                name=getattr(provider, "name", "Provider"),
                provider_type=provider_type or "custom",
                status=_provider_status(provider),
                readiness=readiness,
                reason=reason,
                recommended_action=recommended_action,
            )
        )

    required_type_states: list[ProviderRequiredTypeReadiness] = []
    missing_required_types: list[str] = []
    for provider_type, label in REQUIRED_PROVIDER_TYPES:
        live_count = live_by_type.get(provider_type, 0)
        sandbox_count = sandbox_by_type.get(provider_type, 0)
        mock_count = mock_by_type.get(provider_type, 0)
        unconfigured_count = unconfigured_by_type.get(provider_type, 0)
        inactive_count = inactive_by_type.get(provider_type, 0)
        degraded_count = degraded_by_type.get(provider_type, 0)
        failed_count = failed_by_type.get(provider_type, 0)

        if live_count:
            status = "ready"
        elif failed_count:
            status = "failed"
            missing_required_types.append(provider_type)
        elif degraded_count:
            status = "degraded"
            missing_required_types.append(provider_type)
        elif mock_count:
            status = "mock"
            missing_required_types.append(provider_type)
        elif sandbox_count:
            status = "sandbox"
            missing_required_types.append(provider_type)
        elif unconfigured_count or inactive_count:
            status = "unconfigured"
            missing_required_types.append(provider_type)
        else:
            status = "missing"
            missing_required_types.append(provider_type)

        required_type_states.append(
            ProviderRequiredTypeReadiness(
                provider_type=provider_type,
                label=label,
                live_count=live_count,
                sandbox_count=sandbox_count + mock_count,
                unconfigured_count=unconfigured_count + inactive_count + degraded_count + failed_count,
                status=status,
            )
        )

    live_providers = sum(1 for item in items if item.readiness == "live")
    sandbox_providers = sum(1 for item in items if item.readiness == "sandbox")
    mock_providers = sum(1 for item in items if item.readiness == "mock")
    unconfigured_providers = sum(1 for item in items if item.readiness == "unconfigured")
    inactive_providers = sum(1 for item in items if item.readiness == "inactive")
    degraded_providers = sum(1 for item in items if item.readiness == "degraded")
    failed_providers = sum(1 for item in items if item.readiness == "failed")
    ready_required_count = sum(1 for item in required_type_states if item.status == "ready")
    readiness_score = round((ready_required_count / len(required_type_states)) * 100)
    readiness_score = max(
        0,
        readiness_score
        - min(
            30,
            (sandbox_providers + mock_providers + unconfigured_providers + degraded_providers + failed_providers) * 5,
        ),
    )

    recommended_actions = [item.recommended_action for item in items if item.readiness != "live"]
    if not recommended_actions and not missing_required_types:
        recommended_actions = [
            "Provider production configuration is complete; keep pre-release checks and audit evidence current."
        ]
    elif missing_required_types:
        missing_labels = [
            item.label for item in required_type_states if item.provider_type in missing_required_types
        ]
        recommended_actions.insert(0, f"Complete required provider types: {', '.join(missing_labels)}.")

    return ProviderReadinessSummary(
        tenant_id=tenant_id,
        total_providers=len(provider_list),
        live_providers=live_providers,
        sandbox_providers=sandbox_providers,
        mock_providers=mock_providers,
        unconfigured_providers=unconfigured_providers,
        inactive_providers=inactive_providers,
        degraded_providers=degraded_providers,
        failed_providers=failed_providers,
        readiness_score=readiness_score,
        production_ready=not missing_required_types and live_providers > 0,
        missing_required_types=missing_required_types,
        required_types=required_type_states,
        items=items,
        recommended_actions=recommended_actions,
    )
