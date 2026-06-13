"""Integration Sync Adapters

Sync adapters for third-party integration providers.
"""

from app.integrations.sync.base import BaseSyncAdapter, SyncResult, IssueData, ProjectData
from app.integrations.sync.zentao import ZenTaoSyncAdapter
from app.integrations.sync.jira import JiraSyncAdapter
from app.integrations.sync.confluence import ConfluenceSyncAdapter

# Registry of sync adapters by provider type
SYNC_ADAPTERS = {
    "zentao": ZenTaoSyncAdapter,
    "jira": JiraSyncAdapter,
    "confluence": ConfluenceSyncAdapter,
}


def get_sync_adapter(provider_type: str, config: dict) -> BaseSyncAdapter:
    """Get a sync adapter instance for the given provider type.

    Args:
        provider_type: Provider type (zentao/jira/confluence)
        config: Configuration dictionary with credentials

    Returns:
        Appropriate sync adapter instance

    Raises:
        ValueError: If provider type is not supported
    """
    adapter_class = SYNC_ADAPTERS.get(provider_type.lower())
    if not adapter_class:
        raise ValueError(f"No sync adapter for provider type: {provider_type}")
    return adapter_class(config)


__all__ = [
    "BaseSyncAdapter",
    "SyncResult",
    "IssueData",
    "ProjectData",
    "ZenTaoSyncAdapter",
    "JiraSyncAdapter",
    "ConfluenceSyncAdapter",
    "get_sync_adapter",
]
