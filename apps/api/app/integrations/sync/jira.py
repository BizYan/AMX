"""JIRA Sync Adapter

Sync adapter for Atlassian JIRA.
https://www.atlassian.com/software/jira
"""

from typing import Any

from app.integrations.sync.base import (
    BaseSyncAdapter,
    IssueData,
    ProjectData,
    SyncResult,
)


class JiraSyncAdapter(BaseSyncAdapter):
    """Sync adapter for JIRA REST API.

    JIRA provides a REST API at /rest/api/2/ for accessing
    projects, issues, and workflows.
    """

    async def test_connection(self) -> bool:
        """Test connection to JIRA API.

        Returns:
            True if API returns valid response, False otherwise.
        """
        import httpx

        try:
            url = f"{self.base_url}/rest/api/2/myself"
            headers = self._build_auth_headers()

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers, auth=self._get_auth())
                return response.status_code == 200
        except Exception:
            return False

    async def fetch_projects(self) -> list[ProjectData]:
        """Fetch all projects from JIRA.

        Returns:
            List of ProjectData objects.
        """
        import httpx

        projects = []
        try:
            url = f"{self.base_url}/rest/api/2/project"
            headers = self._build_auth_headers()

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers, auth=self._get_auth())
                if response.status_code == 200:
                    items = response.json()
                    for item in items:
                        projects.append(ProjectData(
                            external_id=str(item.get("id", "")),
                            name=item.get("name", ""),
                            description=item.get("description", ""),
                            external_url=f"{self.base_url}/browse/{item.get('key', '')}",
                            metadata={
                                "key": item.get("key", ""),
                                "lead": item.get("lead", {}).get("displayName", ""),
                            },
                        ))
        except Exception:
            pass

        return projects

    async def fetch_issues(
        self,
        project_key: str | None = None,
        updated_after: str | None = None,
    ) -> list[IssueData]:
        """Fetch issues from JIRA.

        Args:
            project_key: Project key to filter by (e.g., 'PROJ').
            updated_after: Optional ISO timestamp to filter by update time.

        Returns:
            List of IssueData objects.
        """
        import httpx

        issues = []
        target_project = project_key or self.project_key

        try:
            jql_parts = []
            if target_project:
                jql_parts.append(f'project = "{target_project}"')
            if updated_after:
                jql_parts.append(f'updated >= "{updated_after}"')

            jql = " AND ".join(jql_parts) if jql_parts else ""
            url = f"{self.base_url}/rest/api/2/search"

            headers = self._build_auth_headers()
            params = {
                "jql": jql,
                "maxResults": 100,
                "fields": "summary,description,status,priority,assignee,created,updated",
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers, auth=self._get_auth(), params=params)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("issues", [])
                    for item in items:
                        issues.append(self._jira_issue_to_issue(item))
        except Exception:
            pass

        return issues

    async def push_update(self, issue_id: str, data: dict[str, Any]) -> bool:
        """Push an update to an issue in JIRA.

        Args:
            issue_id: JIRA issue key (e.g., 'PROJ-123').
            data: Update data containing field-value pairs.

        Returns:
            True if update was successful, False otherwise.
        """
        import httpx

        try:
            url = f"{self.base_url}/rest/api/2/issue/{issue_id}"
            headers = self._build_auth_headers()

            # Convert flat data to JIRA update format
            update_data = {"fields": data}

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.put(url, headers=headers, auth=self._get_auth(), json=update_data)
                return response.status_code == 200
        except Exception:
            return False

    async def sync_project(
        self,
        project_key: str,
        direction: str = "both",
    ) -> SyncResult:
        """Sync a JIRA project with local system.

        Args:
            project_key: JIRA project key.
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
        # JIRA uses Basic Auth with email and API token
        return (self.config.get("username", ""), self.api_token)

    def _jira_issue_to_issue(self, issue: dict) -> IssueData:
        """Convert JIRA issue to standardized IssueData.

        Args:
            issue: JIRA issue data.

        Returns:
            IssueData object.
        """
        fields = issue.get("fields", {})
        assignee = fields.get("assignee", {}) or {}

        return IssueData(
            external_id=issue.get("key", ""),
            title=fields.get("summary", ""),
            description=self._strip_html(fields.get("description", "")),
            status=fields.get("status", {}).get("name", ""),
            priority=fields.get("priority", {}).get("name", ""),
            assignee=assignee.get("displayName", ""),
            created_at=fields.get("created", ""),
            updated_at=fields.get("updated", ""),
            external_url=f"{self.base_url}/browse/{issue.get('key', '')}",
            metadata={
                "issue_type": fields.get("issuetype", {}).get("name", ""),
                "project": issue.get("fields", {}).get("project", {}).get("key", ""),
            },
        )

    def _strip_html(self, text: str) -> str:
        """Strip HTML tags from text.

        Args:
            text: Text potentially containing HTML.

        Returns:
            Plain text with HTML removed.
        """
        import re
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        return text.strip()