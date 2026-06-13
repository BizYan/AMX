"""Provider production readiness aggregation."""

from collections.abc import Iterable
from uuid import UUID

from app.domains.providers.capability import is_live_configured, is_sandbox_provider
from app.domains.providers.models import ProviderStatus
from app.domains.providers.schemas import (
    ProviderReadinessItem,
    ProviderReadinessSummary,
    ProviderRequiredTypeReadiness,
)


REQUIRED_PROVIDER_TYPES = [
    ("llm", "LLM 生成"),
    ("graphify", "Graphify 图谱"),
    ("gitnexus", "GitNexus 代码索引"),
]


def _provider_id(provider) -> UUID:
    return provider.id


def _provider_type(provider) -> str:
    return str(getattr(provider, "provider_type", "") or "").lower()


def _provider_status(provider) -> str:
    return str(getattr(provider, "status", "") or "")


def _classify_provider(provider) -> tuple[str, str, str]:
    provider_type = _provider_type(provider)
    status = _provider_status(provider)

    if status != ProviderStatus.ACTIVE.value:
        return (
            "inactive",
            "Provider 未启用",
            "启用 Provider 后再纳入生产调度，或从生产配置中移除。",
        )
    if is_sandbox_provider(provider):
        return (
            "sandbox",
            "Provider 使用 sandbox/mock/test/demo 配置",
            f"为 {getattr(provider, 'name', 'Provider')} 配置真实服务凭据和生产模式。",
        )
    if not is_live_configured(provider):
        return (
            "unconfigured",
            "Provider 缺少真实凭据或必要生产配置",
            f"补齐 {getattr(provider, 'name', 'Provider')} 的 api_key/token/service_key 与服务端点。",
        )
    return (
        "ready",
        f"{provider_type or 'provider'} 已具备生产配置",
        "定期运行联调测试并保留审计证据。",
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
    unconfigured_by_type: dict[str, int] = {}
    inactive_by_type: dict[str, int] = {}

    for provider in provider_list:
        readiness, reason, recommended_action = _classify_provider(provider)
        provider_type = _provider_type(provider)
        if readiness == "ready":
            live_by_type[provider_type] = live_by_type.get(provider_type, 0) + 1
        elif readiness == "sandbox":
            sandbox_by_type[provider_type] = sandbox_by_type.get(provider_type, 0) + 1
        elif readiness == "unconfigured":
            unconfigured_by_type[provider_type] = unconfigured_by_type.get(provider_type, 0) + 1
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
        unconfigured_count = unconfigured_by_type.get(provider_type, 0)
        inactive_count = inactive_by_type.get(provider_type, 0)
        if live_count:
            status = "ready"
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
                sandbox_count=sandbox_count,
                unconfigured_count=unconfigured_count + inactive_count,
                status=status,
            )
        )

    live_providers = sum(1 for item in items if item.readiness == "ready")
    sandbox_providers = sum(1 for item in items if item.readiness == "sandbox")
    unconfigured_providers = sum(1 for item in items if item.readiness == "unconfigured")
    inactive_providers = sum(1 for item in items if item.readiness == "inactive")
    ready_required_count = sum(1 for item in required_type_states if item.status == "ready")
    readiness_score = round((ready_required_count / len(required_type_states)) * 100)
    readiness_score = max(0, readiness_score - min(20, (sandbox_providers + unconfigured_providers) * 5))

    recommended_actions = [
        item.recommended_action
        for item in items
        if item.readiness != "ready"
    ]
    if not recommended_actions and not missing_required_types:
        recommended_actions = ["Provider 生产配置齐全；继续按发布前联调和审计流程验证。"]
    elif missing_required_types:
        missing_labels = [
            item.label for item in required_type_states if item.provider_type in missing_required_types
        ]
        recommended_actions.insert(0, f"补齐核心 Provider 类型：{', '.join(missing_labels)}。")

    return ProviderReadinessSummary(
        tenant_id=tenant_id,
        total_providers=len(provider_list),
        live_providers=live_providers,
        sandbox_providers=sandbox_providers,
        unconfigured_providers=unconfigured_providers,
        inactive_providers=inactive_providers,
        readiness_score=readiness_score,
        production_ready=not missing_required_types and live_providers > 0,
        missing_required_types=missing_required_types,
        required_types=required_type_states,
        items=items,
        recommended_actions=recommended_actions,
    )
