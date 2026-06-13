"""Project-scoped document lifecycle policy defaults and persistence."""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.projects.schemas import (
    DocumentLifecyclePolicyResponse,
    DocumentLifecyclePolicyUpdate,
    DocumentLifecyclePublishGates,
    DocumentLifecycleStatus,
    DocumentLifecycleTransition,
)
from app.domains.projects.service import ProjectSettingsService


DEFAULT_STATUS_LABELS = {
    "draft": "草稿",
    "writing": "编写中",
    "pending_review": "待评审",
    "review": "评审",
    "in_review": "评审中",
    "revision_required": "待修订",
    "approved": "已批准",
    "published": "已发布",
    "archived": "已归档",
}

DEFAULT_TRANSITIONS = {
    "draft": {"writing", "pending_review", "review", "archived"},
    "writing": {"draft", "pending_review", "review", "archived"},
    "pending_review": {"review", "in_review", "revision_required", "approved", "archived"},
    "review": {"draft", "in_review", "revision_required", "approved", "archived"},
    "in_review": {"revision_required", "approved", "archived"},
    "revision_required": {"writing", "pending_review", "review", "archived"},
    "approved": {"review", "revision_required", "published", "archived"},
    "published": {"archived"},
    "archived": set(),
}


def default_document_lifecycle_policy() -> DocumentLifecyclePolicyResponse:
    """Return a fresh default policy matching the platform's established flow."""
    return DocumentLifecyclePolicyResponse(
        revision=1,
        statuses=[
            DocumentLifecycleStatus(key=key, label=label)
            for key, label in DEFAULT_STATUS_LABELS.items()
        ],
        transitions=[
            DocumentLifecycleTransition(from_status=source, to_status=target)
            for source, targets in DEFAULT_TRANSITIONS.items()
            for target in sorted(targets)
        ],
        require_reason_for=[],
        publish_gates=DocumentLifecyclePublishGates(),
    )


class ProjectDocumentLifecyclePolicyService:
    """Read and update the validated document lifecycle policy for a project."""

    SETTINGS_KEY = "document_lifecycle"

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings_service = ProjectSettingsService(db)

    async def get_policy(self, project_id: UUID) -> DocumentLifecyclePolicyResponse:
        settings = await self.settings_service.get_settings(project_id)
        raw_policy = (settings.settings_json or {}).get(self.SETTINGS_KEY) if settings else None
        if not raw_policy:
            return default_document_lifecycle_policy()
        return DocumentLifecyclePolicyResponse.model_validate(raw_policy)

    async def update_policy(
        self,
        project_id: UUID,
        policy_update: DocumentLifecyclePolicyUpdate,
    ) -> DocumentLifecyclePolicyResponse:
        enabled_statuses = {status.key for status in policy_update.statuses}
        disabled_active_statuses = await self.find_disabled_active_statuses(
            project_id,
            enabled_statuses,
        )
        if disabled_active_statuses:
            raise ValueError(
                "Cannot disable statuses used by active documents: "
                + ", ".join(disabled_active_statuses)
            )

        settings = await self.settings_service.get_settings(project_id)
        settings_json = deepcopy(settings.settings_json or {}) if settings else {}
        current_raw = settings_json.get(self.SETTINGS_KEY)
        current_revision = int((current_raw or {}).get("revision") or 0)
        policy = DocumentLifecyclePolicyResponse(
            **policy_update.model_dump(),
            revision=current_revision + 1,
        )
        settings_json[self.SETTINGS_KEY] = policy.model_dump(mode="json")
        await self.settings_service.upsert_settings(
            project_id=project_id,
            settings=settings_json,
        )
        return policy

    async def find_disabled_active_statuses(
        self,
        project_id: UUID,
        enabled_statuses: set[str],
    ) -> list[str]:
        """Return persisted document statuses that the proposed policy disables."""
        from app.domains.documents.models import Document

        result = await self.db.execute(
            select(Document.status, func.count(Document.id))
            .where(
                Document.project_id == project_id,
                Document.deleted_at.is_(None),
                Document.status.notin_(enabled_statuses),
            )
            .group_by(Document.status)
        )
        return sorted(row.status for row in result.all())
