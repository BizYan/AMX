"""ZenTao Sync Adapter

Sync adapter for ZenTao (禅道) project management tool.
https://www.zentao.net
"""

from datetime import datetime
from typing import Any
import hashlib
import hmac
import base64

from app.integrations.sync.base import (
    BaseSyncAdapter,
    IssueData,
    ProjectData,
    SyncResult,
)


class ZenTaoSyncAdapter(BaseSyncAdapter):
    """Sync adapter for ZenTao REST API.

    ZenTao provides a REST API at /api/v1/ for accessing
    projects, tasks, bugs, and stories.
    """

    async def test_connection(self) -> bool:
        """Test connection to ZenTao API.

        Returns:
            True if API returns valid response, False otherwise.
        """
        import httpx

        try:
            url = f"{self.base_url}/api/v1/projects"
            headers = self._build_auth_headers()
            headers["token"] = self.api_token

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)
                return response.status_code == 200
        except Exception:
            return False

    async def fetch_projects(self) -> list[ProjectData]:
        """Fetch all projects from ZenTao.

        Returns:
            List of ProjectData objects.
        """
        import httpx

        projects = []
        try:
            url = f"{self.base_url}/api/v1/projects"
            headers = self._build_auth_headers()
            headers["token"] = self.api_token

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("data", {}).get("projects", [])
                    for item in items:
                        projects.append(ProjectData(
                            external_id=str(item.get("id", "")),
                            name=item.get("name", ""),
                            description=item.get("desc", ""),
                            external_url=f"{self.base_url}/project-view-{item.get('id', '')}.html",
                            metadata={"status": item.get("status", "")},
                        ))
        except Exception:
            pass

        return projects

    async def fetch_issues(
        self,
        project_key: str | None = None,
        updated_after: str | None = None,
    ) -> list[IssueData]:
        """Fetch tasks/stories from ZenTao.

        Args:
            project_key: Project ID to filter by.
            updated_after: Optional ISO timestamp to filter by update time.

        Returns:
            List of IssueData objects.
        """
        import httpx

        issues = []
        try:
            # ZenTao uses type-specific endpoints: /tasks, /stories, /bugs
            endpoint = f"{self.base_url}/api/v1/{'tasks' if not project_key else 'tasks'}"

            params = {}
            if project_key:
                params["projectID"] = project_key
            if updated_after:
                params["modifiedDate"] = updated_after

            headers = self._build_auth_headers()
            headers["token"] = self.api_token

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(endpoint, headers=headers, params=params)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("data", {}).get("tasks", [])
                    for item in items:
                        issues.append(self._task_to_issue(item))
        except Exception:
            pass

        return issues

    async def push_update(self, issue_id: str, data: dict[str, Any]) -> bool:
        """Push an update to a task in ZenTao.

        Args:
            issue_id: Task ID to update.
            data: Update data containing field-value pairs.

        Returns:
            True if update was successful, False otherwise.
        """
        import httpx

        try:
            url = f"{self.base_url}/api/v1/tasks/{issue_id}"
            headers = self._build_auth_headers()
            headers["token"] = self.api_token

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.put(url, headers=headers, json=data)
                return response.status_code == 200
        except Exception:
            return False

    async def sync_project(
        self,
        project_key: str,
        direction: str = "both",
    ) -> SyncResult:
        """Sync a ZenTao project with local system.

        Args:
            project_key: ZenTao project ID.
            direction: Sync direction - "pull", "push", or "both".

        Returns:
            SyncResult with sync statistics.
        """
        result = SyncResult(success=True)

        if direction in ("pull", "both"):
            issues = await self.fetch_issues(project_key=project_key)
            result.synced_issues = len(issues)

        return result

    def _task_to_issue(self, task: dict) -> IssueData:
        """Convert ZenTao task to standardized IssueData.

        Args:
            task: ZenTao task data.

        Returns:
            IssueData object.
        """
        return IssueData(
            external_id=str(task.get("id", "")),
            title=task.get("name", ""),
            description=task.get("desc", ""),
            status=self._map_status(task.get("status", "")),
            priority=self._map_priority(task.get("pri", "")),
            assignee=task.get("assignedTo", ""),
            created_at=task.get("openedDate", ""),
            updated_at=task.get("modifiedDate", task.get("lastEditedDate", "")),
            external_url=f"{self.base_url}/task-view-{task.get('id', '')}.html",
            metadata={
                "project_id": task.get("project", ""),
                "story_id": task.get("story", ""),
                "execution_id": task.get("execution", ""),
            },
        )

    def _map_status(self, zentao_status: str) -> str:
        """Map ZenTao status to standardized status.

        Args:
            zentao_status: ZenTao status string.

        Returns:
            Standardized status string.
        """
        status_map = {
            "wait": "open",
            "doing": "in_progress",
            "done": "completed",
            "closed": "closed",
        }
        return status_map.get(zentao_status.lower(), zentao_status)

    def _map_priority(self, zentao_priority: str) -> str:
        """Map ZenTao priority to standardized priority.

        Args:
            zentao_priority: ZenTao priority string/number.

        Returns:
            Standardized priority string.
        """
        priority_map = {
            "1": "highest",
            "2": "high",
            "3": "medium",
            "4": "low",
            "5": "lowest",
        }
        if isinstance(zentao_priority, str):
            return priority_map.get(zentao_priority.lower(), "medium")
        return priority_map.get(str(zentao_priority), "medium")