"""Document export tool adapter backed by the export domain service."""

from typing import Any
from uuid import UUID

from app.domains.agent.tools.base import BaseToolAdapter, ToolExecutionError
from app.domains.export.models import ExportType
from app.domains.export.service import ExportService
from sqlalchemy.ext.asyncio import AsyncSession


class DocumentExportToolAdapter(BaseToolAdapter):
    """Tool adapter for document export operations.

    Supports:
    - Export to Markdown
    - Export to DOCX/Word
    - Export to PPTX
    - Export project delivery package
    """

    def __init__(self, db: AsyncSession | None = None):
        self.db = db

    @property
    def tool_name(self) -> str:
        return "document_export"

    async def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute document export.

        Args:
            input_data: {
                "document_id": str,
                "format": "markdown" | "docx" | "pdf" | "json",
                "options": {...}
            }

        Returns:
            {"success": bool, "data": {...}, "error": str | None}
        """
        document_id = input_data.get("document_id")
        project_id = input_data.get("project_id")
        export_format = str(input_data.get("format", "markdown")).lower()
        if export_format == "docx":
            export_format = ExportType.WORD.value
        tenant_id = self._coerce_uuid(input_data.get("tenant_id"))
        created_by = self._coerce_uuid(input_data.get("created_by"))

        if not tenant_id:
            raise ToolExecutionError(
                "tenant_id is required for document export",
                tool_name=self.tool_name,
            )

        try:
            if self.db is not None:
                return await self._execute_with_service(
                    ExportService(self.db),
                    document_id=document_id,
                    project_id=project_id,
                    export_format=export_format,
                    tenant_id=tenant_id,
                    created_by=created_by,
                    input_data=input_data,
                )
            else:
                from app.db.session import AsyncSessionLocal

                async with AsyncSessionLocal() as db:
                    return await self._execute_with_service(
                        ExportService(db),
                        document_id=document_id,
                        project_id=project_id,
                        export_format=export_format,
                        tenant_id=tenant_id,
                        created_by=created_by,
                        input_data=input_data,
                    )
        except ToolExecutionError:
            raise
        except Exception as e:
            raise ToolExecutionError(
                str(e),
                tool_name=self.tool_name,
                details={"document_id": document_id, "project_id": project_id, "format": export_format},
            )

    @staticmethod
    def _coerce_uuid(value: Any) -> UUID | None:
        if value is None or isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    async def _execute_with_service(
        self,
        service: ExportService,
        *,
        document_id: Any,
        project_id: Any,
        export_format: str,
        tenant_id: UUID,
        created_by: UUID | None,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        options = input_data.get("options") or {}
        variables = input_data.get("variables") or options.get("variables") or {}
        title = input_data.get("title") or options.get("title")
        template_id = self._coerce_uuid(input_data.get("template_id") or options.get("template_id"))

        if export_format == ExportType.PROJECT_PACKAGE.value:
            project_uuid = self._coerce_uuid(project_id)
            if not project_uuid:
                raise ToolExecutionError("project_id is required for project package export", tool_name=self.tool_name)
            document_ids = [
                item for item in (
                    self._coerce_uuid(value)
                    for value in (input_data.get("document_ids") or options.get("document_ids") or [])
                )
                if item is not None
            ]
            job = await service.export_project_package(
                project_id=project_uuid,
                tenant_id=tenant_id,
                document_ids=document_ids or None,
                title=title,
                include_drafts=bool(input_data.get("include_drafts") or options.get("include_drafts") or False),
                include_manifest=bool(input_data.get("include_manifest", options.get("include_manifest", True))),
                variables=variables,
                created_by=created_by,
            )
            return self._job_output(job)

        document_uuid = self._coerce_uuid(document_id)
        if not document_uuid:
            raise ToolExecutionError("document_id is required", tool_name=self.tool_name)

        if export_format == ExportType.WORD.value:
            job = await service.export_word(
                document_id=document_uuid,
                template_id=template_id,
                tenant_id=tenant_id,
                variables=variables,
                title=title,
                created_by=created_by,
            )
        elif export_format == ExportType.MARKDOWN.value:
            job = await service.export_markdown(
                document_id=document_uuid,
                tenant_id=tenant_id,
                variables=variables,
                title=title,
                created_by=created_by,
            )
        elif export_format == ExportType.PPTX.value:
            job = await service.export_pptx(
                document_id=document_uuid,
                template_id=template_id,
                tenant_id=tenant_id,
                variables=variables,
                title=title,
                created_by=created_by,
            )
        else:
            raise ToolExecutionError(f"Unsupported format: {export_format}", tool_name=self.tool_name)
        return self._job_output(job)

    @staticmethod
    def _job_output(job: Any) -> dict[str, Any]:
        artifacts = [
            {
                "artifact_id": str(artifact.id),
                "filename": artifact.filename,
                "content_type": artifact.content_type,
                "file_size": artifact.file_size,
                "storage_path": artifact.storage_path,
                "download_url": f"/api/v1/exports/artifacts/{artifact.id}/download",
            }
            for artifact in (getattr(job, "artifacts", None) or [])
        ]
        first_artifact = artifacts[0] if artifacts else {}
        return {
            "success": str(getattr(job, "status", "")) == "completed",
            "summary": "Document export job completed." if str(getattr(job, "status", "")) == "completed" else "Document export job did not complete.",
            "data": {
                "job_id": str(job.id),
                "status": job.status,
                "export_type": job.export_type,
                "document_id": str(job.document_id) if job.document_id else None,
                "project_id": str(job.project_id),
                "file_path": job.output_path,
                "file_size": first_artifact.get("file_size", 0),
                "artifact_count": len(artifacts),
                "artifacts": artifacts,
            },
            "next_actions": [
                f"下载 {first_artifact.get('filename')}"
            ] if first_artifact else ["查看导出中心确认任务状态。"],
        }
