"""Confluence Sync Adapter

Sync adapter for Atlassian Confluence.
https://www.atlassian.com/software/confluence
"""

from typing import Any

from app.integrations.sync.base import (
    BaseSyncAdapter,
    IssueData,
    ProjectData,
    SyncResult,
)


class ConfluenceSyncAdapter(BaseSyncAdapter):
    """Sync adapter for Confluence REST API.

    Confluence provides a REST API at /wiki/rest/api/ for accessing
    spaces, pages, and content.
    """

    async def test_connection(self) -> bool:
        """Test connection to Confluence API.

        Returns:
            True if API returns valid response, False otherwise.
        """
        import httpx

        try:
            url = f"{self.base_url}/wiki/rest/api/user/current"
            headers = self._build_auth_headers()

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers, auth=self._get_auth())
                return response.status_code == 200
        except Exception:
            return False

    async def fetch_projects(self) -> list[ProjectData]:
        """Fetch all spaces from Confluence.

        Returns:
            List of ProjectData objects.
        """
        import httpx

        projects = []
        try:
            url = f"{self.base_url}/wiki/rest/api/space"
            headers = self._build_auth_headers()
            params = {"limit": 50}

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers, auth=self._get_auth(), params=params)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("results", [])
                    for item in items:
                        projects.append(ProjectData(
                            external_id=str(item.get("id", "")),
                            name=item.get("name", ""),
                            description=item.get("description", {}).get("plain", {}).get("value", ""),
                            external_url=f"{self.base_url}/wiki/spaces/{item.get('key', '')}",
                            metadata={"key": item.get("key", "")},
                        ))
        except Exception:
            pass

        return projects

    async def fetch_issues(
        self,
        project_key: str | None = None,
        updated_after: str | None = None,
    ) -> list[IssueData]:
        """Fetch pages from Confluence.

        Args:
            project_key: Space key to filter by (e.g., 'DEMO').
            updated_after: Optional ISO timestamp to filter by update time.

        Returns:
            List of IssueData objects.
        """
        import httpx

        issues = []
        target_space = project_key or self.project_key

        try:
            url = f"{self.base_url}/wiki/rest/api/content"
            headers = self._build_auth_headers()

            params = {
                "type": "page",
                "limit": 50,
                "expand": "title,version,body,ancestors",
            }
            if target_space:
                params["spaceKey"] = target_space
            if updated_after:
                params["modifiedDate"] = updated_after

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers, auth=self._get_auth(), params=params)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("results", [])
                    for item in items:
                        issues.append(self._confluence_page_to_issue(item))
        except Exception:
            pass

        return issues

    async def push_update(self, issue_id: str, data: dict[str, Any]) -> bool:
        """Push an update to a page in Confluence.

        Args:
            issue_id: Page ID to update.
            data: Update data containing title, body, etc.

        Returns:
            True if update was successful, False otherwise.
        """
        import httpx

        try:
            url = f"{self.base_url}/wiki/rest/api/content/{issue_id}"
            headers = self._build_auth_headers()

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # First get current version
                get_response = await client.get(url, headers=headers, auth=self._get_auth())
                if get_response.status_code != 200:
                    return False

                current = get_response.json()
                new_version = int(current.get("version", {}).get("number", 1)) + 1

                # Update with new version
                update_data = {
                    "version": {"number": new_version},
                    "title": data.get("title", current.get("title", "")),
                    "type": "page",
                    "body": {
                        "storage": {
                            "representation": "storage",
                            "value": data.get("body", current.get("body", {}).get("storage", {}).get("value", "")),
                        }
                    },
                }

                put_response = await client.put(url, headers=headers, auth=self._get_auth(), json=update_data)
                return put_response.status_code == 200
        except Exception:
            return False

    async def sync_project(
        self,
        project_key: str,
        direction: str = "both",
    ) -> SyncResult:
        """Sync a Confluence space with local system.

        Args:
            project_key: Confluence space key.
            direction: Sync direction - "pull", "push", or "both".

        Returns:
            SyncResult with sync statistics.
        """
        result = SyncResult(success=True)

        if direction in ("pull", "both"):
            issues = await self.fetch_issues(project_key=project_key)
            result.synced_issues = len(issues)

        return result

    def _get_auth(self) -> tuple[str, str]:
        """Get authentication tuple for httpx.

        Returns:
            Tuple of (username, api_token).
        """
        return (self.config.get("username", ""), self.api_token)

    def _confluence_page_to_issue(self, page: dict) -> IssueData:
        """Convert Confluence page to standardized IssueData.

        Args:
            page: Confluence page data.

        Returns:
            IssueData object.
        """
        body_storage = page.get("body", {}).get("storage", {})

        return IssueData(
            external_id=str(page.get("id", "")),
            title=page.get("title", ""),
            description=body_storage.get("value", ""),
            status="published" if page.get("status") == "current" else "draft",
            priority="",
            assignee=page.get("ancestors", [{}])[-1].get("displayName", "") if page.get("ancestors") else "",
            created_at=page.get("creationDate", ""),
            updated_at=page.get("version", {}).get("when", ""),
            external_url=f"{self.base_url}/wiki/pages/{page.get('id', '')}",
            metadata={
                "space": page.get("space", {}).get("key", ""),
                "version": page.get("version", {}).get("number", ""),
            },
        )