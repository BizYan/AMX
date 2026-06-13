"""GitNexus Provider Adapter

Implements GitNexusContract with fixture backing for testing.
"""

import json
from pathlib import Path
from typing import Any

import httpx

from app.domains.providers.contracts import GitNexusContract, GitNexusOutput, ProviderError
from app.integrations.gitnexus.config import load_gitnexus_runtime_config


class GitNexusProvider(GitNexusContract):
    """GitNexus provider with fixture support for testing.

    If fixture_data is provided, uses it instead of calling the actual endpoint.
    """

    def __init__(self, config: dict[str, Any], fixture_data: dict[str, Any] | None = None):
        """Initialize GitNexus provider.

        Args:
            config: Provider configuration containing:
                - endpoint: GitNexus API endpoint URL
                - api_key: Optional API key
                - timeout: Request timeout in seconds
            fixture_data: Optional fixture data to use instead of real API calls
        """
        self.config = config
        runtime_config = load_gitnexus_runtime_config(config)
        self.endpoint = runtime_config.endpoint
        self.api_key = runtime_config.api_key
        self.health_path = runtime_config.health_path
        self.timeout = runtime_config.timeout
        self.fixture_data = fixture_data

    async def check_health(self) -> dict[str, Any]:
        """Check the GitNexus service health endpoint."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.endpoint}{self.health_path}",
                    headers=headers,
                )
                if response.status_code >= 400:
                    raise ProviderError(
                        message=f"GitNexus health check failed: {response.status_code}",
                        details={"status_code": response.status_code, "response": response.text},
                    )
                if hasattr(response, "json"):
                    return response.json()
                return json.loads(response.text)
        except httpx.RequestError as e:
            raise ProviderError(message=f"GitNexus health request failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise ProviderError(message=f"Invalid JSON from GitNexus health endpoint: {str(e)}")

    async def fetch_commits(
        self,
        repo_url: str,
        params: dict[str, Any] | None = None,
    ) -> GitNexusOutput:
        """Fetch commits from a repository.

        Args:
            repo_url: URL of the repository
            params: Query parameters (branch, since, until, limit, etc.)

        Returns:
            GitNexusOutput with commit data

        Raises:
            ProviderError: If fetch fails
        """
        params = params or {}

        # Use fixture data if available
        if self.fixture_data is not None:
            return self._process_commits_fixture(self.fixture_data, repo_url)

        # Call actual GitNexus endpoint
        return await self._call_gitnexus_api("/commits", repo_url, params)

    async def fetch_issues(
        self,
        repo_url: str,
        params: dict[str, Any] | None = None,
    ) -> GitNexusOutput:
        """Fetch issues from a repository.

        Args:
            repo_url: URL of the repository
            params: Query parameters (state, labels, assignee, etc.)

        Returns:
            GitNexusOutput with issue data

        Raises:
            ProviderError: If fetch fails
        """
        params = params or {}

        # Use fixture data if available
        if self.fixture_data is not None:
            return self._process_issues_fixture(self.fixture_data, repo_url)

        # Call actual GitNexus endpoint
        return await self._call_gitnexus_api("/issues", repo_url, params)

    def _process_commits_fixture(self, fixture: dict[str, Any], repo_url: str) -> GitNexusOutput:
        """Process commits fixture data.

        Args:
            fixture: Fixture data dictionary
            repo_url: Repository URL

        Returns:
            GitNexusOutput with commit data
        """
        commits = fixture.get("commits", [])

        # Inject repo_url into commit metadata
        for commit in commits:
            if "metadata" not in commit:
                commit["metadata"] = {}
            commit["metadata"]["repo_url"] = repo_url

        return GitNexusOutput(
            data=commits,
            metadata=fixture.get("metadata", {}),
        )

    def _process_issues_fixture(self, fixture: dict[str, Any], repo_url: str) -> GitNexusOutput:
        """Process issues fixture data.

        Args:
            fixture: Fixture data dictionary
            repo_url: Repository URL

        Returns:
            GitNexusOutput with issue data
        """
        issues = fixture.get("issues", [])

        # Inject repo_url into issue metadata
        for issue in issues:
            if "metadata" not in issue:
                issue["metadata"] = {}
            issue["metadata"]["repo_url"] = repo_url

        return GitNexusOutput(
            data=issues,
            metadata=fixture.get("metadata", {}),
        )

    async def _call_gitnexus_api(
        self,
        path: str,
        repo_url: str,
        params: dict[str, Any],
    ) -> GitNexusOutput:
        """Call the GitNexus API endpoint.

        Args:
            path: API path (/commits or /issues)
            repo_url: Repository URL
            params: Query parameters

        Returns:
            GitNexusOutput from API response

        Raises:
            ProviderError: If API call fails
        """
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "repo_url": repo_url,
            "params": params,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.endpoint}{path}",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

                return GitNexusOutput(
                    data=data.get("data", []),
                    metadata=data.get("metadata"),
                )
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                message=f"GitNexus API error: {e.response.status_code}",
                details={"status_code": e.response.status_code, "response": e.response.text},
            )
        except httpx.RequestError as e:
            raise ProviderError(message=f"GitNexus request failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise ProviderError(message=f"Invalid JSON from GitNexus: {str(e)}")


def load_fixture(fixture_path: str | Path) -> dict[str, Any]:
    """Load fixture data from a JSON file.

    Args:
        fixture_path: Path to fixture JSON file

    Returns:
        Fixture data dictionary

    Raises:
        FileNotFoundError: If fixture file doesn't exist
        json.JSONDecodeError: If fixture is not valid JSON
    """
    path = Path(fixture_path)
    if not path.exists():
        raise FileNotFoundError(f"Fixture file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# Default fixture paths
DEFAULT_FIXTURES_PATH = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "gitnexus"
