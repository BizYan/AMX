"""Base Sync Adapter

Abstract base class for third-party integration sync adapters.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IssueData:
    """Standardized issue/task data from external systems."""

    external_id: str
    title: str
    description: str = ""
    status: str = ""
    priority: str = ""
    assignee: str = ""
    created_at: str = ""
    updated_at: str = ""
    external_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectData:
    """Standardized project data from external systems."""

    external_id: str
    name: str
    description: str = ""
    external_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SyncResult:
    """Result of a sync operation."""

    success: bool
    synced_issues: int = 0
    synced_projects: int = 0
    errors: list[str] = field(default_factory=list)
    last_sync_at: str = ""

    def add_error(self, error: str):
        """Add an error to the result."""
        self.errors.append(error)


class BaseSyncAdapter(ABC):
    """Abstract base class for sync adapters.

    All sync adapters must implement these methods to provide
    standardized sync operations for their external systems.
    """

    def __init__(self, config: dict[str, Any]):
        """Initialize sync adapter with configuration.

        Args:
            config: Configuration dictionary containing:
                - base_url: Base URL of the external system API
                - api_token: API token for authentication
                - project_key: Project key/ID for the project to sync
                - timeout: Optional request timeout in seconds
        """
        self.config = config
        self.base_url = config.get("base_url", "").rstrip("/")
        self.api_token = config.get("api_token", "")
        self.project_key = config.get("project_key", "")
        self.timeout = config.get("timeout", 30)

    @abstractmethod
    async def test_connection(self) -> bool:
        """Test the connection to the external system.

        Returns:
            True if connection is successful, False otherwise.
        """
        pass

    @abstractmethod
    async def fetch_projects(self) -> list[ProjectData]:
        """Fetch all projects from the external system.

        Returns:
            List of ProjectData objects.
        """
        pass

    @abstractmethod
    async def fetch_issues(
        self,
        project_key: str | None = None,
        updated_after: str | None = None,
    ) -> list[IssueData]:
        """Fetch issues/tasks from the external system.

        Args:
            project_key: Optional project key to filter by.
            updated_after: Optional ISO timestamp to filter by update time.

        Returns:
            List of IssueData objects.
        """
        pass

    @abstractmethod
    async def push_update(self, issue_id: str, data: dict[str, Any]) -> bool:
        """Push an update to an issue in the external system.

        Args:
            issue_id: External issue ID to update.
            data: Update data to push.

        Returns:
            True if update was successful, False otherwise.
        """
        pass

    def _build_headers(self) -> dict[str, str]:
        """Build common HTTP headers for API requests.

        Returns:
            Dictionary of headers.
        """
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _build_auth_headers(self) -> dict[str, str]:
        """Build authentication headers.

        Returns:
            Dictionary of headers with authentication.
        """
        headers = self._build_headers()
        return headers

    def _validate_config(self, required_fields: list[str]) -> list[str]:
        """Validate that required config fields are present.

        Args:
            required_fields: List of required field names.

        Returns:
            List of missing field names (empty if all present).
        """
        missing = []
        for field_name in required_fields:
            if not self.config.get(field_name):
                missing.append(field_name)
        return missing