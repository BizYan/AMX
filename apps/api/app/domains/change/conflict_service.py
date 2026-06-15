"""Persistent document conflict governance helpers."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.change.models import ChangePriority, ChangeType, ConflictStatus, DocumentConflict, DocumentConflictDecision
from app.domains.change.schemas import ConflictScanResponse, DocumentConflictListResponse
from app.domains.change.service import ChangeService, TraceabilityService
from app.domains.documents.models import Document
from app.models.identity import User
from app.models.projects import Project


MUTABLE_EVIDENCE_KEYS = {
    "description",
    "detected_at",
    "last_detected_at",
    "summary",
}


def build_conflict_fingerprint(
    *,
    tenant_id: UUID,
    project_id: UUID,
    rule_key: str,
    primary_document_id: UUID,
    related_document_id: UUID | None,
    evidence: dict[str, Any],
) -> str:
    """Build a stable fingerprint from rule identity and immutable evidence."""
    stable_evidence = {
        key: value
        for key, value in evidence.items()
        if key not in MUTABLE_EVIDENCE_KEYS
    }
    canonical = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "project_id": str(project_id),
            "rule_key": rule_key,
            "primary_document_id": str(primary_document_id),
            "related_document_id": str(related_document_id) if related_document_id else None,
            "evidence": stable_evidence,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ConflictGovernanceService:
    """Persist and query deterministic conflict findings."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve_default_assignment(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        primary_document_id: UUID,
        related_document_id: UUID | None,
    ) -> tuple[UUID | None, str | None]:
        """Resolve the default conflict owner from document and project ownership."""
        primary_owner = await self.db.scalar(
            select(Document.created_by).where(
                Document.id == primary_document_id,
                Document.tenant_id == tenant_id,
            )
        )
        if primary_owner:
            return primary_owner, "primary_document_owner"

        if related_document_id:
            related_owner = await self.db.scalar(
                select(Document.created_by).where(
                    Document.id == related_document_id,
                    Document.tenant_id == tenant_id,
                )
            )
            if related_owner:
                return related_owner, "related_document_owner"

        project_owner = await self.db.scalar(
            select(Project.owner_id).where(
                Project.id == project_id,
                Project.tenant_id == tenant_id,
            )
        )
        if project_owner:
            return project_owner, "project_owner"
        return None, None

    def record_decision(
        self,
        *,
        conflict: DocumentConflict,
        actor_id: UUID,
        action: str,
        previous_status: str | None,
        resulting_status: str,
        reason: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> DocumentConflictDecision:
        """Append one governance history record for a conflict mutation."""
        decision = DocumentConflictDecision(
            tenant_id=conflict.tenant_id,
            project_id=conflict.project_id,
            conflict_id=conflict.id,
            actor_id=actor_id,
            action=action,
            previous_status=previous_status,
            resulting_status=resulting_status,
            reason=reason,
            evidence_json=evidence or {},
        )
        self.db.add(decision)
        return decision

    async def get_conflict_for_update(
        self,
        *,
        tenant_id: UUID,
        conflict_id: UUID,
    ) -> DocumentConflict:
        conflict = await self.get_conflict(tenant_id=tenant_id, conflict_id=conflict_id)
        if not conflict:
            raise ValueError("Document conflict not found")
        return conflict

    async def require_project_owner(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_id: UUID,
        message: str,
    ) -> None:
        owner_id = await self.db.scalar(
            select(Project.owner_id).where(
                Project.id == project_id,
                Project.tenant_id == tenant_id,
            )
        )
        if owner_id != actor_id:
            raise PermissionError(message)

    async def require_conflict_assignee_or_owner(
        self,
        *,
        conflict: DocumentConflict,
        actor_id: UUID,
    ) -> None:
        if conflict.assignee_user_id == actor_id:
            return
        await self.require_project_owner(
            tenant_id=conflict.tenant_id,
            project_id=conflict.project_id,
            actor_id=actor_id,
            message="Only conflict assignee or project owner can complete analysis",
        )

    async def assign_conflict(
        self,
        *,
        tenant_id: UUID,
        conflict_id: UUID,
        actor_id: UUID,
        assignee_user_id: UUID,
        reason: str,
    ) -> DocumentConflict:
        conflict = await self.get_conflict_for_update(
            tenant_id=tenant_id,
            conflict_id=conflict_id,
        )
        await self.require_project_owner(
            tenant_id=tenant_id,
            project_id=conflict.project_id,
            actor_id=actor_id,
            message="Only project owner can assign conflicts",
        )
        assignee = await self.db.scalar(
            select(User.id).where(
                User.id == assignee_user_id,
                User.tenant_id == tenant_id,
                User.deleted_at.is_(None),
            )
        )
        if not assignee:
            raise ValueError("Assignee not found")

        now = datetime.now(timezone.utc)
        previous_status = conflict.status
        conflict.assignee_user_id = assignee_user_id
        conflict.assignment_source = "manual"
        conflict.assigned_at = now
        if conflict.status == ConflictStatus.UNASSIGNED.value:
            conflict.status = ConflictStatus.ANALYSIS.value

        self.record_decision(
            conflict=conflict,
            actor_id=actor_id,
            action="assign",
            previous_status=previous_status,
            resulting_status=conflict.status,
            reason=reason,
            evidence={"assignee_user_id": str(assignee_user_id), "assignment_source": "manual"},
        )
        await self.db.flush()
        return conflict

    async def complete_analysis(
        self,
        *,
        tenant_id: UUID,
        conflict_id: UUID,
        actor_id: UUID,
        reason: str,
        evidence: dict[str, Any],
    ) -> DocumentConflict:
        conflict = await self.get_conflict_for_update(
            tenant_id=tenant_id,
            conflict_id=conflict_id,
        )
        await self.require_conflict_assignee_or_owner(conflict=conflict, actor_id=actor_id)
        if conflict.status != ConflictStatus.ANALYSIS.value:
            raise ValueError("Conflict must be in analysis status")

        previous_status = conflict.status
        conflict.status = ConflictStatus.DECISION.value
        self.record_decision(
            conflict=conflict,
            actor_id=actor_id,
            action="complete_analysis",
            previous_status=previous_status,
            resulting_status=conflict.status,
            reason=reason,
            evidence=evidence,
        )
        await self.db.flush()
        return conflict

    async def reject_conflict(
        self,
        *,
        tenant_id: UUID,
        conflict_id: UUID,
        actor_id: UUID,
        reason: str,
        evidence: dict[str, Any],
    ) -> DocumentConflict:
        if not reason.strip():
            raise ValueError("Rejection reason is required")
        conflict = await self.get_conflict_for_update(
            tenant_id=tenant_id,
            conflict_id=conflict_id,
        )
        await self.require_project_owner(
            tenant_id=tenant_id,
            project_id=conflict.project_id,
            actor_id=actor_id,
            message="Only project owner can reject conflicts",
        )
        if conflict.status != ConflictStatus.DECISION.value:
            raise ValueError("Conflict must be in decision status")

        previous_status = conflict.status
        conflict.status = ConflictStatus.REJECTED.value
        self.record_decision(
            conflict=conflict,
            actor_id=actor_id,
            action="reject",
            previous_status=previous_status,
            resulting_status=conflict.status,
            reason=reason,
            evidence=evidence,
        )
        await self.db.flush()
        return conflict

    async def accept_revision(
        self,
        *,
        tenant_id: UUID,
        conflict_id: UUID,
        actor_id: UUID,
        suggested_revision: str,
        reason: str,
        evidence: dict[str, Any],
    ) -> DocumentConflict:
        if not suggested_revision.strip():
            raise ValueError("Suggested revision is required")
        if not reason.strip():
            raise ValueError("Acceptance reason is required")

        conflict = await self.get_conflict_for_update(
            tenant_id=tenant_id,
            conflict_id=conflict_id,
        )
        await self.require_project_owner(
            tenant_id=tenant_id,
            project_id=conflict.project_id,
            actor_id=actor_id,
            message="Only project owner can accept conflict revisions",
        )
        if conflict.status != ConflictStatus.DECISION.value:
            raise ValueError("Conflict must be in decision status")
        if conflict.linked_change_request_id:
            raise ValueError("Conflict already has a linked change request")

        target_document_id = await self.resolve_change_target_document_id(conflict)
        change_request = await ChangeService(self.db).create_change_request(
            tenant_id=tenant_id,
            project_id=conflict.project_id,
            source_doc_id=conflict.primary_document_id,
            target_doc_id=target_document_id,
            change_type=ChangeType.CORRECTION.value,
            description=suggested_revision,
            requested_by=actor_id,
            priority=ChangePriority.HIGH.value if conflict.severity == "high" else ChangePriority.MEDIUM.value,
            rationale=(
                f"Accepted revision for document conflict {conflict.id}: {reason}"
            ),
            impact_analysis=conflict.summary,
            risk_assessment=json.dumps(
                {
                    "conflict_id": str(conflict.id),
                    "rule_key": conflict.rule_key,
                    "severity": conflict.severity,
                    "evidence": evidence,
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
        )

        previous_status = conflict.status
        now = datetime.now(timezone.utc)
        conflict.status = ConflictStatus.REVISION_ACCEPTED.value
        conflict.linked_change_request_id = change_request.id
        conflict.accepted_revision_json = {
            "suggested_revision": suggested_revision,
            "evidence": evidence,
        }
        conflict.revision_accepted_at = now
        self.record_decision(
            conflict=conflict,
            actor_id=actor_id,
            action="accept_revision",
            previous_status=previous_status,
            resulting_status=conflict.status,
            reason=reason,
            evidence={
                "change_request_id": str(change_request.id),
                "suggested_revision": suggested_revision,
                **evidence,
            },
        )
        await self.db.flush()
        return conflict

    async def resolve_change_target_document_id(self, conflict: DocumentConflict) -> UUID | None:
        if conflict.related_document_id:
            return conflict.related_document_id

        candidate_parent_ids = conflict.evidence_json.get("candidate_parent_ids")
        if isinstance(candidate_parent_ids, list) and candidate_parent_ids:
            try:
                candidate_id = UUID(str(candidate_parent_ids[0]))
            except ValueError:
                return None
            exists = await self.db.scalar(
                select(Document.id).where(
                    Document.id == candidate_id,
                    Document.tenant_id == conflict.tenant_id,
                    Document.project_id == conflict.project_id,
                    Document.deleted_at.is_(None),
                )
            )
            return exists
        return None

    async def persist_new_conflict(
        self,
        conflict: DocumentConflict,
    ) -> tuple[DocumentConflict, bool]:
        """Insert a fingerprint once or return the concurrently created row."""
        try:
            async with self.db.begin_nested():
                self.db.add(conflict)
                await self.db.flush()
            return conflict, True
        except IntegrityError:
            existing = await self.db.scalar(
                select(DocumentConflict).where(
                    DocumentConflict.tenant_id == conflict.tenant_id,
                    DocumentConflict.project_id == conflict.project_id,
                    DocumentConflict.fingerprint == conflict.fingerprint,
                )
            )
            if existing:
                return existing, False
            raise

    async def scan_project(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
    ) -> ConflictScanResponse:
        scan_id = uuid4()
        now = datetime.now(timezone.utc)
        findings = await TraceabilityService(self.db).find_project_conflicts(
            project_id=project_id,
            tenant_id=tenant_id,
        )
        existing_result = await self.db.execute(
            select(DocumentConflict).where(
                DocumentConflict.tenant_id == tenant_id,
                DocumentConflict.project_id == project_id,
            )
        )
        existing_by_fingerprint = {
            conflict.fingerprint: conflict
            for conflict in existing_result.scalars().all()
        }

        created = 0
        refreshed = 0
        reopened = 0
        seen: set[str] = set()
        items: list[DocumentConflict] = []
        for finding in findings:
            evidence = dict(finding.evidence)
            fingerprint = build_conflict_fingerprint(
                tenant_id=tenant_id,
                project_id=project_id,
                rule_key=finding.rule_key or finding.conflict_type,
                primary_document_id=finding.document_id,
                related_document_id=finding.related_document_id,
                evidence=evidence,
            )
            seen.add(fingerprint)
            conflict = existing_by_fingerprint.get(fingerprint)
            assignee_user_id, assignment_source = await self.resolve_default_assignment(
                tenant_id=tenant_id,
                project_id=project_id,
                primary_document_id=finding.document_id,
                related_document_id=finding.related_document_id,
            )
            if conflict is None:
                candidate = DocumentConflict(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    rule_key=finding.rule_key or finding.conflict_type,
                    fingerprint=fingerprint,
                    severity=finding.severity,
                    status=(
                        ConflictStatus.ANALYSIS.value
                        if assignee_user_id
                        else ConflictStatus.UNASSIGNED.value
                    ),
                    primary_document_id=finding.document_id,
                    primary_document_version=finding.version_1,
                    related_document_id=finding.related_document_id,
                    related_document_version=finding.related_document_version,
                    summary=finding.description,
                    evidence_json=evidence,
                    first_detected_at=now,
                    last_detected_at=now,
                    last_scan_id=scan_id,
                    assignee_user_id=assignee_user_id,
                    assignment_source=assignment_source,
                    assigned_at=now if assignee_user_id else None,
                )
                conflict, was_created = await self.persist_new_conflict(candidate)
                existing_by_fingerprint[fingerprint] = conflict
                if was_created:
                    created += 1
                    if assignee_user_id:
                        self.record_decision(
                            conflict=conflict,
                            actor_id=assignee_user_id,
                            action="assign",
                            previous_status=None,
                            resulting_status=conflict.status,
                            evidence={"assignment_source": assignment_source},
                        )
                else:
                    refreshed += 1
            else:
                refreshed += 1
                if conflict.status == ConflictStatus.CLOSED.value:
                    conflict.status = ConflictStatus.ANALYSIS.value
                    conflict.closed_at = None
                    reopened += 1
                conflict.severity = finding.severity
                conflict.primary_document_version = finding.version_1
                conflict.related_document_id = finding.related_document_id
                conflict.related_document_version = finding.related_document_version
                conflict.summary = finding.description
                conflict.evidence_json = evidence
                conflict.last_detected_at = now
                conflict.last_scan_id = scan_id
                conflict.absent_since = None
                if assignee_user_id and conflict.assignee_user_id != assignee_user_id:
                    conflict.assignee_user_id = assignee_user_id
                    conflict.assignment_source = assignment_source
                    conflict.assigned_at = now
                    self.record_decision(
                        conflict=conflict,
                        actor_id=assignee_user_id,
                        action="assign",
                        previous_status=conflict.status,
                        resulting_status=conflict.status,
                        evidence={"assignment_source": assignment_source},
                    )
            items.append(conflict)

        marked_absent = 0
        for fingerprint, conflict in existing_by_fingerprint.items():
            if fingerprint not in seen and conflict.absent_since is None:
                conflict.absent_since = now
                marked_absent += 1

        await self.db.flush()
        return ConflictScanResponse(
            scan_id=scan_id,
            project_id=project_id,
            detected=len(findings),
            created=created,
            refreshed=refreshed,
            reopened=reopened,
            marked_absent=marked_absent,
            items=items,
        )

    async def get_conflict(
        self,
        *,
        tenant_id: UUID,
        conflict_id: UUID,
    ) -> DocumentConflict | None:
        result = await self.db.execute(
            select(DocumentConflict).where(
                DocumentConflict.id == conflict_id,
                DocumentConflict.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_project_conflicts(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        severity: str | None = None,
        status: str | None = None,
    ) -> DocumentConflictListResponse:
        filters = [
            DocumentConflict.tenant_id == tenant_id,
            DocumentConflict.project_id == project_id,
        ]
        if severity:
            filters.append(DocumentConflict.severity == severity)
        if status:
            filters.append(DocumentConflict.status == status)
        result = await self.db.execute(
            select(DocumentConflict)
            .where(*filters)
            .order_by(DocumentConflict.last_detected_at.desc())
        )
        items = list(result.scalars().all())
        return DocumentConflictListResponse(items=items, total=len(items))
