"""Change Domain Service

Business logic for change requests, field patches, traceability, and controlled backwrite.
"""

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.change.models import (
    ChangeRequest,
    ChangeRequestComment,
    ChangeStatus,
    ChangeType,
    ConflictStatus,
    DocumentImpactAnalysis,
    DocumentConflict,
    DocumentReference,
    DocumentSyncProposal,
    FieldPatch,
    PatchStatus,
    PatchType,
)
from app.domains.change.schemas import (
    ChangeRequestCreate,
    ChangeRequestUpdate,
    ChangeAuditCommandCenterResponse,
    ChangeAuditCommandCenterSummary,
    ChangeAuditPriorityAction,
    ChangeAuditReleaseGate,
    ChangeAuditRiskItem,
    FieldPatchCreate,
    TraceabilityMatrixItem,
    ImpactAnalysisItem,
    TraceabilityCoverageResponse,
    TraceabilityCoverageSummary,
    TraceabilityGapItem,
    TraceabilityReferenceSuggestion,
    TraceabilitySuggestionAcceptanceItem,
    TraceabilitySuggestionAcceptanceResponse,
    DocumentTraceabilityItem,
    DocumentTraceabilityResponse,
    ConflictItem,
    ConflictAnalysisResponse,
    FullTraceabilityMatrixResponse,
)
from app.domains.documents.models import (
    Document,
    DocumentBaseline,
    DocumentVersion,
    DocumentType,
    DocumentStatus,
)


class ChangeAuditCommandCenterService:
    """Aggregates change, patch, and traceability risks for release review."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_command_center(
        self,
        tenant_id: UUID,
        project_id: UUID | None = None,
    ) -> ChangeAuditCommandCenterResponse:
        change_filters = [
            ChangeRequest.tenant_id == tenant_id,
            ChangeRequest.deleted_at.is_(None),
        ]
        if project_id is not None:
            change_filters.append(ChangeRequest.project_id == project_id)

        change_status_counts = await self._counts_by(
            ChangeRequest.status,
            ChangeRequest.id,
            change_filters,
        )
        priority_counts = await self._counts_by(
            ChangeRequest.priority,
            ChangeRequest.id,
            change_filters,
        )

        patch_filters = [FieldPatch.tenant_id == tenant_id]
        if project_id is not None:
            patch_filters.append(
                FieldPatch.change_request_id.in_(
                    select(ChangeRequest.id).where(*change_filters)
                )
            )

        impact_filters = [
            DocumentImpactAnalysis.tenant_id == tenant_id,
        ]
        proposal_filters = [
            DocumentSyncProposal.tenant_id == tenant_id,
        ]
        if project_id is not None:
            impact_filters.append(DocumentImpactAnalysis.project_id == project_id)
            proposal_filters.append(DocumentSyncProposal.project_id == project_id)

        pending_field_patches = await self._count(
            FieldPatch.id,
            [*patch_filters, FieldPatch.status == PatchStatus.PENDING.value],
        )
        open_impact_analyses = await self._count(
            DocumentImpactAnalysis.id,
            [*impact_filters, DocumentImpactAnalysis.status == "open"],
        )
        critical_or_high_open_impacts = await self._count(
            DocumentImpactAnalysis.id,
            [
                *impact_filters,
                DocumentImpactAnalysis.status == "open",
                DocumentImpactAnalysis.impact_level.in_(["critical", "high"]),
            ],
        )
        pending_sync_proposals = await self._count(
            DocumentSyncProposal.id,
            [*proposal_filters, DocumentSyncProposal.status == "pending"],
        )
        impact_level_counts = await self._counts_by(
            DocumentImpactAnalysis.impact_level,
            DocumentImpactAnalysis.id,
            [*impact_filters, DocumentImpactAnalysis.status == "open"],
        )

        conflict_filters = [
            DocumentConflict.tenant_id == tenant_id,
            DocumentConflict.status.notin_([
                ConflictStatus.CLOSED.value,
                ConflictStatus.REJECTED.value,
            ]),
        ]
        if project_id is not None:
            conflict_filters.append(DocumentConflict.project_id == project_id)
        open_document_conflicts = await self._count(
            DocumentConflict.id,
            conflict_filters,
        )
        high_open_document_conflicts = await self._count(
            DocumentConflict.id,
            [
                *conflict_filters,
                DocumentConflict.severity == "high",
            ],
        )
        expired_conflict_risk_acceptances = await self._count(
            DocumentConflict.id,
            [
                *conflict_filters,
                DocumentConflict.status == ConflictStatus.RISK_ACCEPTED.value,
                DocumentConflict.risk_acceptance_expires_at < datetime.now(timezone.utc),
            ],
        )
        revision_accepted_conflicts = await self._count(
            DocumentConflict.id,
            [
                *conflict_filters,
                DocumentConflict.status == ConflictStatus.REVISION_ACCEPTED.value,
            ],
        )

        critical_or_high_open_changes = await self._count(
            ChangeRequest.id,
            [
                *change_filters,
                ChangeRequest.status.in_([ChangeStatus.DRAFT.value, ChangeStatus.OPEN.value]),
                ChangeRequest.priority.in_(["critical", "high"]),
            ],
        )
        approved_unapplied_changes = change_status_counts.get(ChangeStatus.APPROVED.value, 0)
        summary = ChangeAuditCommandCenterSummary(
            total_changes=sum(change_status_counts.values()),
            draft_changes=change_status_counts.get(ChangeStatus.DRAFT.value, 0),
            open_changes=change_status_counts.get(ChangeStatus.OPEN.value, 0),
            approved_unapplied_changes=approved_unapplied_changes,
            critical_or_high_open_changes=critical_or_high_open_changes,
            pending_field_patches=pending_field_patches,
            open_impact_analyses=open_impact_analyses,
            critical_or_high_open_impacts=critical_or_high_open_impacts,
            pending_sync_proposals=pending_sync_proposals,
            open_document_conflicts=open_document_conflicts,
            high_open_document_conflicts=high_open_document_conflicts,
            expired_conflict_risk_acceptances=expired_conflict_risk_acceptances,
            revision_accepted_conflicts=revision_accepted_conflicts,
        )
        risk_items = self._build_risk_items(summary)
        release_gate = self._build_release_gate(summary, risk_items)
        priority_actions = self._build_priority_actions(summary)

        return ChangeAuditCommandCenterResponse(
            scope="project" if project_id else "tenant",
            project_id=project_id,
            release_gate=release_gate,
            summary=summary,
            change_status_counts=change_status_counts,
            priority_counts=priority_counts,
            impact_level_counts=impact_level_counts,
            risk_items=risk_items,
            priority_actions=priority_actions,
        )

    async def _count(self, column: Any, filters: list[Any]) -> int:
        value = await self.db.scalar(select(func.count(column)).where(*filters))
        return int(value or 0)

    async def _counts_by(self, group_column: Any, count_column: Any, filters: list[Any]) -> dict[str, int]:
        result = await self.db.execute(
            select(group_column, func.count(count_column)).where(*filters).group_by(group_column)
        )
        return {
            str(key): int(count)
            for key, count in result.all()
            if key is not None
        }

    def _build_risk_items(self, summary: ChangeAuditCommandCenterSummary) -> list[ChangeAuditRiskItem]:
        risks: list[ChangeAuditRiskItem] = []
        if summary.critical_or_high_open_changes:
            risks.append(ChangeAuditRiskItem(
                code="critical_open_changes",
                severity="critical",
                title="存在高优先级未关闭变更",
                detail="关键或高优先级变更仍处于草稿/打开状态，发布前必须完成审批或关闭。",
                count=summary.critical_or_high_open_changes,
                href="/audit",
            ))
        if summary.pending_field_patches:
            risks.append(ChangeAuditRiskItem(
                code="pending_field_patches",
                severity="high",
                title="字段级回写补丁待审",
                detail="文档字段补丁尚未人工确认，可能导致生成内容与正式文档不一致。",
                count=summary.pending_field_patches,
                href="/documents/contradictions",
            ))
        if summary.critical_or_high_open_impacts:
            risks.append(ChangeAuditRiskItem(
                code="open_impact_analyses",
                severity="high",
                title="高影响追溯分析未关闭",
                detail="上游文档变更仍有高影响分析处于打开状态，需要确认下游影响。",
                count=summary.critical_or_high_open_impacts,
                href="/documents/contradictions",
            ))
        elif summary.open_impact_analyses:
            risks.append(ChangeAuditRiskItem(
                code="open_impact_analyses",
                severity="medium",
                title="追溯影响分析未关闭",
                detail="仍有影响分析等待处理，发布前建议完成复核。",
                count=summary.open_impact_analyses,
                href="/documents/contradictions",
            ))
        if summary.pending_sync_proposals:
            risks.append(ChangeAuditRiskItem(
                code="pending_sync_proposals",
                severity="high",
                title="同步建议待处理",
                detail="文档追溯链路已生成同步建议，需要接受或拒绝后再进入发布门禁。",
                count=summary.pending_sync_proposals,
                href="/documents/contradictions",
            ))
        if summary.high_open_document_conflicts:
            risks.append(ChangeAuditRiskItem(
                code="high_open_document_conflicts",
                severity="critical",
                title="High-severity document conflicts are unresolved",
                detail="Persisted document conflicts with high severity must be rejected, risk-accepted, revised, or closed before release.",
                count=summary.high_open_document_conflicts,
                href="/documents/contradictions",
            ))
        if summary.expired_conflict_risk_acceptances:
            risks.append(ChangeAuditRiskItem(
                code="expired_conflict_risk_acceptances",
                severity="critical",
                title="Conflict risk acceptances have expired",
                detail="Accepted conflict risks with expired mitigation windows must be reviewed before release.",
                count=summary.expired_conflict_risk_acceptances,
                href="/documents/contradictions",
            ))
        if summary.revision_accepted_conflicts:
            risks.append(ChangeAuditRiskItem(
                code="revision_accepted_conflicts",
                severity="high",
                title="Accepted conflict revisions need closure",
                detail="Accepted revisions must be applied and verified absent by rescan before release.",
                count=summary.revision_accepted_conflicts,
                href="/documents/contradictions",
            ))
        if summary.approved_unapplied_changes:
            risks.append(ChangeAuditRiskItem(
                code="approved_unapplied_changes",
                severity="medium",
                title="已批准变更尚未应用",
                detail="已批准变更需要应用到目标文档或明确取消，避免发布遗漏。",
                count=summary.approved_unapplied_changes,
                href="/audit",
            ))
        return risks

    def _build_release_gate(
        self,
        summary: ChangeAuditCommandCenterSummary,
        risk_items: list[ChangeAuditRiskItem],
    ) -> ChangeAuditReleaseGate:
        blockers = [
            item.title
            for item in risk_items
            if item.severity in {"critical", "high"}
        ]
        warnings = [
            item.title
            for item in risk_items
            if item.severity == "medium"
        ]
        if blockers:
            return ChangeAuditReleaseGate(
                status="blocked",
                label="发布阻断",
                summary="变更追溯链路仍存在必须处理的高风险项。",
                blockers=blockers,
                warnings=warnings,
            )
        if warnings or summary.open_changes or summary.draft_changes:
            return ChangeAuditReleaseGate(
                status="attention",
                label="需复核",
                summary="没有高风险阻断，但仍有变更或追溯事项建议复核。",
                blockers=[],
                warnings=warnings or ["仍有打开或草稿变更需要确认"],
            )
        return ChangeAuditReleaseGate(
            status="passed",
            label="可进入发布复核",
            summary="未发现未关闭的变更、补丁或追溯影响阻断。",
            blockers=[],
            warnings=[],
        )

    def _build_priority_actions(
        self,
        summary: ChangeAuditCommandCenterSummary,
    ) -> list[ChangeAuditPriorityAction]:
        actions: list[ChangeAuditPriorityAction] = []
        if (
            summary.open_document_conflicts
            or summary.expired_conflict_risk_acceptances
            or summary.revision_accepted_conflicts
        ):
            actions.append(ChangeAuditPriorityAction(
                code="resolve_document_conflicts",
                title="Resolve document conflict governance queue",
                description="Review persisted conflicts, renew or close expired risk acceptances, and verify accepted revisions by rescan.",
                href="/documents/contradictions",
                priority="critical"
                if summary.high_open_document_conflicts or summary.expired_conflict_risk_acceptances
                else "high",
            ))
        if summary.pending_sync_proposals or summary.open_impact_analyses or summary.pending_field_patches:
            actions.append(ChangeAuditPriorityAction(
                code="resolve_traceability_risks",
                title="处理文档追溯与同步建议",
                description="进入冲突检测与追溯处置页，完成影响分析、同步建议和字段补丁复核。",
                href="/documents/contradictions",
                priority="critical" if summary.critical_or_high_open_impacts else "high",
            ))
        if summary.critical_or_high_open_changes or summary.approved_unapplied_changes:
            actions.append(ChangeAuditPriorityAction(
                code="review_change_queue",
                title="复核变更队列",
                description="确认高优先级变更、已批准未应用变更和发布前审计证据。",
                href="/audit",
                priority="high",
            ))
        if not actions:
            actions.append(ChangeAuditPriorityAction(
                code="maintain_audit_review",
                title="保持发布前审计复核",
                description="当前没有阻断项，发布前继续保留审计证据和变更追溯快照。",
                href="/audit",
                priority="medium",
            ))
        return actions


class ChangeService:
    """Service for change request management.

    Handles CRUD operations for change requests with workflow states
    (draft -> open -> approved/rejected -> applied/cancelled).
    """

    def __init__(self, db: AsyncSession):
        """Initialize change service.

        Args:
            db: Async database session
        """
        self.db = db

    async def create_change_request(
        self,
        tenant_id: UUID,
        project_id: UUID,
        source_doc_id: UUID | None,
        target_doc_id: UUID | None,
        change_type: str,
        description: str,
        requested_by: UUID | None = None,
        priority: str = "medium",
        rationale: str | None = None,
        impact_analysis: str | None = None,
        risk_assessment: str | None = None,
    ) -> ChangeRequest:
        """Create a new change request.

        Args:
            tenant_id: Tenant UUID
            project_id: Project UUID
            source_doc_id: Source document ID (document being changed)
            target_doc_id: Target document ID (document that caused the change)
            change_type: Type of change (correction/enhancement/dependency)
            description: Description of the change
            requested_by: User ID of requester
            priority: Priority level (critical/high/medium/low)
            rationale: Reason for the change
            impact_analysis: Analysis of change impact
            risk_assessment: Risk assessment of the change

        Returns:
            Created ChangeRequest
        """
        if requested_by is None:
            raise ValueError("requested_by is required")

        change_request = ChangeRequest(
            tenant_id=tenant_id,
            project_id=project_id,
            source_document_id=source_doc_id,
            target_document_id=target_doc_id,
            change_type=change_type,
            priority=priority,
            status=ChangeStatus.DRAFT.value,
            description=description,
            rationale=rationale,
            impact_analysis=impact_analysis,
            risk_assessment=risk_assessment,
            requested_by=requested_by,
        )

        # Capture source document version if provided
        if source_doc_id:
            source_doc = await self._get_document(source_doc_id, tenant_id)
            if source_doc:
                change_request.source_document_version = source_doc.version

        # Capture target document version if provided
        if target_doc_id:
            target_doc = await self._get_document(target_doc_id, tenant_id)
            if target_doc:
                change_request.target_document_version = target_doc.version

        self.db.add(change_request)
        await self.db.flush()
        await self.db.refresh(change_request)
        return change_request

    async def _get_document(self, document_id: UUID, tenant_id: UUID) -> Document | None:
        """Get document by ID with tenant filter.

        Args:
            document_id: Document UUID
            tenant_id: Tenant UUID

        Returns:
            Document if found, None otherwise
        """
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_change_request(
        self,
        change_request_id: UUID,
        tenant_id: UUID,
    ) -> ChangeRequest | None:
        """Get change request by ID.

        Args:
            change_request_id: Change request UUID
            tenant_id: Tenant UUID

        Returns:
            ChangeRequest if found, None otherwise
        """
        result = await self.db.execute(
            select(ChangeRequest).where(
                ChangeRequest.id == change_request_id,
                ChangeRequest.tenant_id == tenant_id,
                ChangeRequest.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_change_requests(
        self,
        tenant_id: UUID,
        project_id: UUID | None = None,
        status: str | None = None,
        change_type: str | None = None,
        priority: str | None = None,
        requested_by: UUID | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[ChangeRequest], int]:
        """List change requests with filters.

        Args:
            tenant_id: Tenant UUID
            project_id: Optional project filter
            status: Optional status filter
            change_type: Optional change type filter
            priority: Optional priority filter
            requested_by: Optional requester filter
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of ChangeRequests, total count)
        """
        base_query = select(ChangeRequest).where(
            ChangeRequest.tenant_id == tenant_id,
            ChangeRequest.deleted_at.is_(None),
        )

        if project_id is not None:
            base_query = base_query.where(ChangeRequest.project_id == project_id)
        if status is not None:
            base_query = base_query.where(ChangeRequest.status == status)
        if change_type is not None:
            base_query = base_query.where(ChangeRequest.change_type == change_type)
        if priority is not None:
            base_query = base_query.where(ChangeRequest.priority == priority)
        if requested_by is not None:
            base_query = base_query.where(ChangeRequest.requested_by == requested_by)

        # Count total
        count_query = select(func.count(ChangeRequest.id)).select_from(base_query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get paginated results
        result = await self.db.execute(
            base_query
            .offset(skip)
            .limit(limit)
            .order_by(ChangeRequest.updated_at.desc())
        )
        change_requests = list(result.scalars().all())

        return change_requests, total

    async def update_change_request(
        self,
        change_request_id: UUID,
        tenant_id: UUID,
        updates: ChangeRequestUpdate,
    ) -> ChangeRequest | None:
        """Update a change request.

        Args:
            change_request_id: Change request UUID
            tenant_id: Tenant UUID
            updates: Update data

        Returns:
            Updated ChangeRequest if found, None otherwise
        """
        change_request = await self.get_change_request(change_request_id, tenant_id)
        if not change_request:
            return None

        # Can only update in draft status
        if change_request.status != ChangeStatus.DRAFT.value:
            raise ValueError("Can only update change requests in draft status")

        if updates.change_type is not None:
            change_request.change_type = updates.change_type
        if updates.priority is not None:
            change_request.priority = updates.priority
        if updates.description is not None:
            change_request.description = updates.description
        if updates.rationale is not None:
            change_request.rationale = updates.rationale
        if updates.impact_analysis is not None:
            change_request.impact_analysis = updates.impact_analysis
        if updates.risk_assessment is not None:
            change_request.risk_assessment = updates.risk_assessment

        await self.db.flush()
        await self.db.refresh(change_request)
        return change_request

    async def submit_for_review(
        self,
        change_request_id: UUID,
        tenant_id: UUID,
    ) -> ChangeRequest | None:
        """Submit change request for review.

        Args:
            change_request_id: Change request UUID
            tenant_id: Tenant UUID

        Returns:
            Updated ChangeRequest if found, None otherwise
        """
        change_request = await self.get_change_request(change_request_id, tenant_id)
        if not change_request:
            return None

        if change_request.status != ChangeStatus.DRAFT.value:
            raise ValueError("Can only submit draft change requests for review")

        change_request.status = ChangeStatus.OPEN.value
        await self.db.flush()
        await self.db.refresh(change_request)
        return change_request

    async def approve_change_request(
        self,
        change_request_id: UUID,
        tenant_id: UUID,
        reviewer_id: UUID,
    ) -> ChangeRequest | None:
        """Approve a change request.

        Args:
            change_request_id: Change request UUID
            tenant_id: Tenant UUID
            reviewer_id: User ID of reviewer

        Returns:
            Updated ChangeRequest if found, None otherwise
        """
        change_request = await self.get_change_request(change_request_id, tenant_id)
        if not change_request:
            return None

        if change_request.status != ChangeStatus.OPEN.value:
            raise ValueError("Can only approve open change requests")

        change_request.status = ChangeStatus.APPROVED.value
        change_request.reviewed_by = reviewer_id
        change_request.reviewed_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(change_request)
        return change_request

    async def reject_change_request(
        self,
        change_request_id: UUID,
        tenant_id: UUID,
        reviewer_id: UUID,
        reason: str,
    ) -> ChangeRequest | None:
        """Reject a change request.

        Args:
            change_request_id: Change request UUID
            tenant_id: Tenant UUID
            reviewer_id: User ID of reviewer
            reason: Reason for rejection

        Returns:
            Updated ChangeRequest if found, None otherwise
        """
        change_request = await self.get_change_request(change_request_id, tenant_id)
        if not change_request:
            return None

        if change_request.status != ChangeStatus.OPEN.value:
            raise ValueError("Can only reject open change requests")

        change_request.status = ChangeStatus.REJECTED.value
        change_request.reviewed_by = reviewer_id
        change_request.reviewed_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(change_request)
        return change_request

    async def apply_change_request(
        self,
        change_request_id: UUID,
        tenant_id: UUID,
    ) -> ChangeRequest | None:
        """Apply a change request by creating new version with patches.

        Args:
            change_request_id: Change request UUID
            tenant_id: Tenant UUID

        Returns:
            Updated ChangeRequest if found, None otherwise
        """
        change_request = await self.get_change_request(change_request_id, tenant_id)
        if not change_request:
            return None

        if change_request.status != ChangeStatus.APPROVED.value:
            raise ValueError("Can only apply approved change requests")

        # Get field patches
        patch_service = FieldPatchService(self.db)
        patches = await patch_service.get_patches_for_change_request(
            change_request_id, tenant_id
        )

        # Apply patches to create new version
        if change_request.source_document_id and patches:
            backwrite_service = ControlledBackwriteService(self.db)
            await backwrite_service.backwrite_with_new_version(
                document_id=change_request.source_document_id,
                patches=patches,
                tenant_id=tenant_id,
                user_id=change_request.requested_by,
            )

        change_request.status = ChangeStatus.APPLIED.value
        change_request.applied_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(change_request)
        return change_request

    async def cancel_change_request(
        self,
        change_request_id: UUID,
        tenant_id: UUID,
    ) -> ChangeRequest | None:
        """Cancel a change request.

        Args:
            change_request_id: Change request UUID
            tenant_id: Tenant UUID

        Returns:
            Updated ChangeRequest if found, None otherwise
        """
        change_request = await self.get_change_request(change_request_id, tenant_id)
        if not change_request:
            return None

        if change_request.status in [ChangeStatus.APPLIED.value, ChangeStatus.CANCELLED.value]:
            raise ValueError("Cannot cancel already applied or cancelled change requests")

        change_request.status = ChangeStatus.CANCELLED.value
        await self.db.flush()
        await self.db.refresh(change_request)
        return change_request

    async def soft_delete_change_request(
        self,
        change_request_id: UUID,
        tenant_id: UUID,
    ) -> ChangeRequest | None:
        """Soft delete a change request.

        Args:
            change_request_id: Change request UUID
            tenant_id: Tenant UUID

        Returns:
            Deleted ChangeRequest if found, None otherwise
        """
        change_request = await self.get_change_request(change_request_id, tenant_id)
        if not change_request:
            return None

        if change_request.status != ChangeStatus.DRAFT.value:
            raise ValueError("Can only delete draft change requests")

        change_request.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(change_request)
        return change_request


class FieldPatchService:
    """Service for field patch management.

    Handles granular field-level changes within change requests.
    """

    def __init__(self, db: AsyncSession):
        """Initialize field patch service.

        Args:
            db: Async database session
        """
        self.db = db

    async def create_field_patch(
        self,
        change_request_id: UUID,
        tenant_id: UUID,
        document_id: UUID,
        field_path: str,
        old_value: str | None,
        new_value: str | None,
        patch_type: str = "replace",
    ) -> FieldPatch:
        """Create a field patch.

        Args:
            change_request_id: Change request UUID
            tenant_id: Tenant UUID
            document_id: Document UUID
            field_path: Path to field (e.g., "sections.0.content")
            old_value: Original value
            new_value: New value
            patch_type: Type of patch (replace/add/remove)

        Returns:
            Created FieldPatch
        """
        # Get document version
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        document = result.scalar_one_or_none()
        if not document:
            raise ValueError("Document not found")

        patch = FieldPatch(
            tenant_id=tenant_id,
            change_request_id=change_request_id,
            document_id=document_id,
            document_version=document.version,
            field_path=field_path,
            old_value=old_value,
            new_value=new_value,
            patch_type=patch_type,
            status=PatchStatus.PENDING.value,
        )
        self.db.add(patch)
        await self.db.flush()
        await self.db.refresh(patch)
        return patch

    async def get_patch(self, patch_id: UUID, tenant_id: UUID) -> FieldPatch | None:
        """Get field patch by ID.

        Args:
            patch_id: Field patch UUID
            tenant_id: Tenant UUID

        Returns:
            FieldPatch if found, None otherwise
        """
        result = await self.db.execute(
            select(FieldPatch).where(
                FieldPatch.id == patch_id,
                FieldPatch.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_patches_for_change_request(
        self,
        change_request_id: UUID,
        tenant_id: UUID,
    ) -> list[FieldPatch]:
        """Get all patches for a change request.

        Args:
            change_request_id: Change request UUID
            tenant_id: Tenant UUID

        Returns:
            List of FieldPatches
        """
        result = await self.db.execute(
            select(FieldPatch).where(
                FieldPatch.change_request_id == change_request_id,
                FieldPatch.tenant_id == tenant_id,
            ).order_by(FieldPatch.created_at)
        )
        return list(result.scalars().all())

    async def approve_field_patch(
        self,
        patch_id: UUID,
        tenant_id: UUID,
        reviewer_id: UUID,
    ) -> FieldPatch | None:
        """Approve a field patch.

        Args:
            patch_id: Field patch UUID
            tenant_id: Tenant UUID
            reviewer_id: User ID of reviewer

        Returns:
            Updated FieldPatch if found, None otherwise
        """
        patch = await self.get_patch(patch_id, tenant_id)
        if not patch:
            return None

        if patch.status != PatchStatus.PENDING.value:
            raise ValueError("Can only approve pending patches")

        patch.status = PatchStatus.APPROVED.value
        patch.reviewed_by = reviewer_id
        patch.reviewed_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(patch)
        return patch

    async def reject_field_patch(
        self,
        patch_id: UUID,
        tenant_id: UUID,
        reviewer_id: UUID,
        reason: str,
    ) -> FieldPatch | None:
        """Reject a field patch.

        Args:
            patch_id: Field patch UUID
            tenant_id: Tenant UUID
            reviewer_id: User ID of reviewer
            reason: Reason for rejection

        Returns:
            Updated FieldPatch if found, None otherwise
        """
        patch = await self.get_patch(patch_id, tenant_id)
        if not patch:
            return None

        if patch.status != PatchStatus.PENDING.value:
            raise ValueError("Can only reject pending patches")

        patch.status = PatchStatus.REJECTED.value
        patch.reviewed_by = reviewer_id
        patch.reviewed_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(patch)
        return patch


class TraceabilityService:
    """Service for requirement traceability and impact analysis.

    Tracks document linkage across the requirement lifecycle:
    URS -> BRD -> PRD -> User Story -> Detailed Design -> Interface Doc -> Data Dict -> Test Case
    """

    DELIVERY_REFERENCE_CHAIN = (
        (DocumentType.URS.value, DocumentType.BRD.value),
        (DocumentType.BRD.value, DocumentType.PRD.value),
        (DocumentType.PRD.value, DocumentType.DETAILED_DESIGN.value),
        (DocumentType.DETAILED_DESIGN.value, DocumentType.TEST_CASE.value),
        (DocumentType.DETAILED_DESIGN.value, DocumentType.DATA_DICTIONARY.value),
    )

    def __init__(self, db: AsyncSession):
        """Initialize traceability service.

        Args:
            db: Async database session
        """
        self.db = db

    async def _get_document(self, document_id: UUID, tenant_id: UUID) -> Document | None:
        """Get a non-deleted tenant document."""
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def create_document_reference(
        self,
        tenant_id: UUID,
        project_id: UUID,
        source_document_id: UUID,
        target_document_id: UUID,
        reference_type: str,
        created_by: UUID,
        source_section: str | None = None,
        target_section: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DocumentReference:
        """Create a version-pinned formal reference between published documents."""
        if source_document_id == target_document_id:
            raise ValueError("Document cannot reference itself")

        source_doc = await self._get_document(source_document_id, tenant_id)
        target_doc = await self._get_document(target_document_id, tenant_id)
        if not source_doc or not target_doc:
            raise ValueError("Document not found")

        if source_doc.project_id != project_id or target_doc.project_id != project_id:
            raise ValueError("Documents must belong to the requested project")

        formal_status = DocumentStatus.PUBLISHED.value
        if source_doc.status != formal_status or target_doc.status != formal_status:
            raise ValueError("Only published documents can be formally referenced")

        reference = DocumentReference(
            tenant_id=tenant_id,
            project_id=project_id,
            source_document_id=source_document_id,
            source_document_version=source_doc.version,
            target_document_id=target_document_id,
            target_document_version=target_doc.version,
            reference_type=reference_type,
            source_section=source_section,
            target_section=target_section,
            status="active",
            created_by=created_by,
            metadata_json=metadata or {},
        )
        self.db.add(reference)
        await self.db.flush()
        await self.db.refresh(reference)
        return reference

    async def list_document_references(
        self,
        tenant_id: UUID,
        document_id: UUID,
        direction: str = "all",
    ) -> list[DocumentReference]:
        """List active references connected to a document."""
        filters = [
            DocumentReference.tenant_id == tenant_id,
            DocumentReference.status == "active",
            DocumentReference.deleted_at.is_(None),
        ]
        if direction == "outgoing":
            filters.append(DocumentReference.source_document_id == document_id)
        elif direction == "incoming":
            filters.append(DocumentReference.target_document_id == document_id)
        else:
            filters.append(
                or_(
                    DocumentReference.source_document_id == document_id,
                    DocumentReference.target_document_id == document_id,
                )
            )

        result = await self.db.execute(
            select(DocumentReference)
            .where(*filters)
            .order_by(DocumentReference.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_traceability_coverage(
        self,
        tenant_id: UUID,
        project_id: UUID,
    ) -> TraceabilityCoverageResponse:
        """Calculate project-level formal traceability coverage and gaps."""
        documents_result = await self.db.execute(
            select(Document)
            .where(
                Document.project_id == project_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
            .order_by(Document.doc_type, Document.title)
        )
        documents = list(documents_result.scalars().all())
        document_by_id = {document.id: document for document in documents}
        published_documents = [
            document
            for document in documents
            if document.status == DocumentStatus.PUBLISHED.value
        ]
        published_ids = {document.id for document in published_documents}

        references_result = await self.db.execute(
            select(DocumentReference).where(
                DocumentReference.project_id == project_id,
                DocumentReference.tenant_id == tenant_id,
                DocumentReference.status == "active",
                DocumentReference.deleted_at.is_(None),
            )
        )
        references = list(references_result.scalars().all())

        referenced_ids: set[UUID] = set()
        existing_pairs: set[tuple[UUID, UUID]] = set()
        incoming_types_by_doc: dict[UUID, set[str]] = {
            document.id: set()
            for document in documents
        }

        for reference in references:
            source_doc = document_by_id.get(reference.source_document_id)
            target_doc = document_by_id.get(reference.target_document_id)
            if not source_doc or not target_doc:
                continue

            existing_pairs.add((source_doc.id, target_doc.id))
            if source_doc.id in published_ids:
                referenced_ids.add(source_doc.id)
            if target_doc.id in published_ids:
                referenced_ids.add(target_doc.id)
            incoming_types_by_doc[target_doc.id].add(source_doc.doc_type)

        open_impact_analyses = await self.db.scalar(
            select(func.count(DocumentImpactAnalysis.id)).where(
                DocumentImpactAnalysis.project_id == project_id,
                DocumentImpactAnalysis.tenant_id == tenant_id,
                DocumentImpactAnalysis.status == "open",
            )
        )
        pending_sync_proposals = await self.db.scalar(
            select(func.count(DocumentSyncProposal.id)).where(
                DocumentSyncProposal.project_id == project_id,
                DocumentSyncProposal.tenant_id == tenant_id,
                DocumentSyncProposal.status == "pending",
            )
        )

        orphan_documents = [
            document
            for document in published_documents
            if document.id not in referenced_ids
        ]
        coverage_rate = (
            round((len(referenced_ids) / len(published_documents)) * 100, 2)
            if published_documents
            else 0.0
        )
        summary = TraceabilityCoverageSummary(
            total_documents=len(documents),
            published_documents=len(published_documents),
            referenced_documents=len(referenced_ids),
            orphan_documents=len(orphan_documents),
            coverage_rate=coverage_rate,
            open_impact_analyses=open_impact_analyses or 0,
            pending_sync_proposals=pending_sync_proposals or 0,
        )

        published_by_type: dict[str, list[Document]] = {}
        for document in published_documents:
            published_by_type.setdefault(document.doc_type, []).append(document)

        upstream_types_by_doc_type: dict[str, list[str]] = {}
        downstream_types_by_doc_type: dict[str, list[str]] = {}
        for source_type, target_type in self.DELIVERY_REFERENCE_CHAIN:
            upstream_types_by_doc_type.setdefault(target_type, []).append(source_type)
            downstream_types_by_doc_type.setdefault(source_type, []).append(target_type)

        gaps = self._build_traceability_gaps(
            documents=documents,
            orphan_documents=orphan_documents,
            published_by_type=published_by_type,
            incoming_types_by_doc=incoming_types_by_doc,
            existing_pairs=existing_pairs,
            upstream_types_by_doc_type=upstream_types_by_doc_type,
            downstream_types_by_doc_type=downstream_types_by_doc_type,
        )
        suggestions = self._build_reference_suggestions(
            published_by_type=published_by_type,
            existing_pairs=existing_pairs,
        )

        return TraceabilityCoverageResponse(
            summary=summary,
            gaps=gaps,
            suggestions=suggestions,
        )

    async def accept_reference_suggestions(
        self,
        tenant_id: UUID,
        project_id: UUID,
        created_by: UUID,
        suggestion_ids: list[str] | None = None,
    ) -> TraceabilitySuggestionAcceptanceResponse:
        """Create formal references from current project coverage suggestions."""
        coverage = await self.get_traceability_coverage(
            tenant_id=tenant_id,
            project_id=project_id,
        )
        requested_ids = set(suggestion_ids or [])
        selected_suggestions = [
            suggestion
            for suggestion in coverage.suggestions
            if not requested_ids or suggestion.id in requested_ids
        ]
        available_ids = {suggestion.id for suggestion in coverage.suggestions}

        items: list[TraceabilitySuggestionAcceptanceItem] = []
        for missing_id in sorted(requested_ids - available_ids):
            parsed_id = self._parse_suggestion_id(missing_id)
            items.append(TraceabilitySuggestionAcceptanceItem(
                suggestion_id=missing_id,
                source_document_id=parsed_id[0] if parsed_id else None,
                target_document_id=parsed_id[1] if parsed_id else None,
                reference_type=parsed_id[2] if parsed_id else "unknown",
                status="skipped",
                reason="suggestion_not_available" if parsed_id else "invalid_suggestion_id",
            ))

        for suggestion in selected_suggestions:
            existing = await self._active_reference_exists(
                tenant_id=tenant_id,
                project_id=project_id,
                source_document_id=suggestion.source_document_id,
                target_document_id=suggestion.target_document_id,
            )
            if existing:
                items.append(TraceabilitySuggestionAcceptanceItem(
                    suggestion_id=suggestion.id,
                    source_document_id=suggestion.source_document_id,
                    target_document_id=suggestion.target_document_id,
                    reference_type=suggestion.reference_type,
                    status="skipped",
                    reference_id=existing.id,
                    reason="reference_already_exists",
                ))
                continue

            reference = await self.create_document_reference(
                tenant_id=tenant_id,
                project_id=project_id,
                source_document_id=suggestion.source_document_id,
                target_document_id=suggestion.target_document_id,
                reference_type=suggestion.reference_type,
                created_by=created_by,
                metadata={
                    "created_from": "traceability_suggestion",
                    "suggestion_id": suggestion.id,
                    "source_document_type": suggestion.source_document_type,
                    "target_document_type": suggestion.target_document_type,
                },
            )
            items.append(TraceabilitySuggestionAcceptanceItem(
                suggestion_id=suggestion.id,
                source_document_id=suggestion.source_document_id,
                target_document_id=suggestion.target_document_id,
                reference_type=suggestion.reference_type,
                status="created",
                reference_id=reference.id,
            ))

        created = sum(1 for item in items if item.status == "created")
        skipped = sum(1 for item in items if item.status == "skipped")
        return TraceabilitySuggestionAcceptanceResponse(
            created=created,
            skipped=skipped,
            items=items,
        )

    async def _active_reference_exists(
        self,
        tenant_id: UUID,
        project_id: UUID,
        source_document_id: UUID,
        target_document_id: UUID,
    ) -> DocumentReference | None:
        result = await self.db.execute(
            select(DocumentReference).where(
                DocumentReference.tenant_id == tenant_id,
                DocumentReference.project_id == project_id,
                DocumentReference.source_document_id == source_document_id,
                DocumentReference.target_document_id == target_document_id,
                DocumentReference.status == "active",
                DocumentReference.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _parse_suggestion_id(suggestion_id: str) -> tuple[UUID, UUID, str] | None:
        parts = suggestion_id.split(":")
        if len(parts) != 3:
            return None
        try:
            return UUID(parts[0]), UUID(parts[1]), parts[2]
        except ValueError:
            return None

    def _build_traceability_gaps(
        self,
        *,
        documents: list[Document],
        orphan_documents: list[Document],
        published_by_type: dict[str, list[Document]],
        incoming_types_by_doc: dict[UUID, set[str]],
        existing_pairs: set[tuple[UUID, UUID]],
        upstream_types_by_doc_type: dict[str, list[str]],
        downstream_types_by_doc_type: dict[str, list[str]],
    ) -> list[TraceabilityGapItem]:
        gaps: list[TraceabilityGapItem] = []
        orphan_ids = {document.id for document in orphan_documents}

        for document in documents:
            if document.status != DocumentStatus.PUBLISHED.value:
                gaps.append(TraceabilityGapItem(
                    code="unpublished",
                    severity="medium",
                    document_id=document.id,
                    document_title=document.title,
                    document_type=document.doc_type,
                    reason="文档尚未发布，无法建立正式追溯引用。",
                    suggested_action="完成评审并发布文档后再纳入追溯覆盖。",
                ))
                continue

            if document.id in orphan_ids:
                gaps.append(TraceabilityGapItem(
                    code="orphan_document",
                    severity="high",
                    document_id=document.id,
                    document_title=document.title,
                    document_type=document.doc_type,
                    reason="该已发布文档还没有任何正式上游或下游引用。",
                    suggested_action="从建议引用中选择合适关系，或手工建立引用。",
                ))

            expected_upstream_types = upstream_types_by_doc_type.get(document.doc_type, [])
            if expected_upstream_types and not (
                incoming_types_by_doc.get(document.id, set()) & set(expected_upstream_types)
            ):
                related = self._first_published_candidate(
                    published_by_type,
                    expected_upstream_types,
                )
                gaps.append(TraceabilityGapItem(
                    code="missing_upstream",
                    severity="high",
                    document_id=document.id,
                    document_title=document.title,
                    document_type=document.doc_type,
                    related_document_id=related.id if related else None,
                    related_document_title=related.title if related else None,
                    related_document_type=related.doc_type if related else None,
                    reason=(
                        "项目中已有可用上游文档，但尚未建立正式引用。"
                        if related
                        else "缺少可引用的已发布上游交付物。"
                    ),
                    suggested_action=(
                        "建立上游到当前文档的正式引用。"
                        if related
                        else "先补齐或发布上游交付物，再建立追溯引用。"
                    ),
                ))

            for downstream_type in downstream_types_by_doc_type.get(document.doc_type, []):
                missing_targets = [
                    target
                    for target in published_by_type.get(downstream_type, [])
                    if (document.id, target.id) not in existing_pairs
                ]
                if not missing_targets:
                    continue

                related = missing_targets[0]
                gaps.append(TraceabilityGapItem(
                    code="missing_downstream",
                    severity="medium",
                    document_id=document.id,
                    document_title=document.title,
                    document_type=document.doc_type,
                    related_document_id=related.id,
                    related_document_title=related.title,
                    related_document_type=related.doc_type,
                    reason="项目中已有下游交付物，但尚未建立正式引用。",
                    suggested_action="建立当前文档到下游文档的正式引用。",
                ))

        return gaps

    def _build_reference_suggestions(
        self,
        *,
        published_by_type: dict[str, list[Document]],
        existing_pairs: set[tuple[UUID, UUID]],
    ) -> list[TraceabilityReferenceSuggestion]:
        suggestions: list[TraceabilityReferenceSuggestion] = []

        for source_type, target_type in self.DELIVERY_REFERENCE_CHAIN:
            for source_doc in published_by_type.get(source_type, []):
                for target_doc in published_by_type.get(target_type, []):
                    if (source_doc.id, target_doc.id) in existing_pairs:
                        continue

                    reference_type = self._suggested_reference_type(target_type)
                    suggestions.append(TraceabilityReferenceSuggestion(
                        id=f"{source_doc.id}:{target_doc.id}:{reference_type}",
                        source_document_id=source_doc.id,
                        source_document_title=source_doc.title,
                        source_document_type=source_doc.doc_type,
                        target_document_id=target_doc.id,
                        target_document_title=target_doc.title,
                        target_document_type=target_doc.doc_type,
                        reference_type=reference_type,
                        reason="符合 URS -> BRD -> PRD -> 详细设计 -> 测试/数据字典交付链路。",
                        suggested_action="一键建立同项目内的正式追溯引用。",
                    ))

        return suggestions

    def _first_published_candidate(
        self,
        published_by_type: dict[str, list[Document]],
        doc_types: list[str],
    ) -> Document | None:
        for doc_type in doc_types:
            candidates = published_by_type.get(doc_type, [])
            if candidates:
                return candidates[0]
        return None

    def _suggested_reference_type(self, target_type: str) -> str:
        if target_type == DocumentType.TEST_CASE.value:
            return "validated_by"
        return "derives_from"

    async def create_document_impact_analysis(
        self,
        tenant_id: UUID,
        document_id: UUID,
        created_by: UUID,
        trigger_type: str = "content_changed",
        summary: str | None = None,
        change_request_id: UUID | None = None,
    ) -> DocumentImpactAnalysis:
        """Create an impact analysis and downstream sync proposals."""
        source_doc = await self._get_document(document_id, tenant_id)
        if not source_doc:
            raise ValueError("Document not found")

        affected_refs = await self._collect_downstream_references(tenant_id, source_doc.id)
        impact_level = self._highest_impact_level([depth for _, _, depth in affected_refs])
        analysis = DocumentImpactAnalysis(
            tenant_id=tenant_id,
            project_id=source_doc.project_id,
            trigger_document_id=source_doc.id,
            trigger_document_version=source_doc.version,
            change_request_id=change_request_id,
            trigger_type=trigger_type,
            impact_level=impact_level,
            status="open" if affected_refs else "resolved",
            summary=summary,
            analysis_json={
                "trigger_document_title": source_doc.title,
                "affected_document_count": len(affected_refs),
                "trigger_type": trigger_type,
            },
            created_by=created_by,
            resolved_at=datetime.now(timezone.utc) if not affected_refs else None,
        )
        self.db.add(analysis)
        await self.db.flush()

        for reference, target_doc, depth in affected_refs:
            level = self._impact_level_for_depth(depth)
            proposal = DocumentSyncProposal(
                tenant_id=tenant_id,
                impact_analysis_id=analysis.id,
                project_id=source_doc.project_id,
                reference_id=reference.id,
                source_document_id=source_doc.id,
                target_document_id=target_doc.id,
                target_document_version=target_doc.version,
                target_section=reference.target_section,
                impact_level=level,
                reason=(
                    f"{source_doc.doc_type.upper()} v{source_doc.version} "
                    f"changed and {target_doc.doc_type.upper()} v{target_doc.version} "
                    "has a formal downstream reference."
                ),
                suggested_action="sync_content",
                candidate_content=self._build_sync_candidate(source_doc, target_doc, reference),
                status="pending",
                metadata_json={"depth": depth, "reference_type": reference.reference_type},
            )
            self.db.add(proposal)

        await self.db.flush()
        await self.db.refresh(analysis)
        return analysis

    async def get_document_impact_analysis(
        self,
        analysis_id: UUID,
        tenant_id: UUID,
    ) -> DocumentImpactAnalysis | None:
        """Get a persisted impact analysis with proposals."""
        result = await self.db.execute(
            select(DocumentImpactAnalysis)
            .options(selectinload(DocumentImpactAnalysis.proposals))
            .where(
                DocumentImpactAnalysis.id == analysis_id,
                DocumentImpactAnalysis.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def apply_sync_proposal(
        self,
        proposal_id: UUID,
        tenant_id: UUID,
        decided_by: UUID,
        decision_note: str | None = None,
        candidate_content: str | None = None,
    ) -> DocumentSyncProposal:
        """Apply a pending sync proposal by creating a new target document version."""
        proposal = await self._get_sync_proposal(proposal_id, tenant_id)
        if not proposal:
            raise ValueError("Sync proposal not found")
        if proposal.status != "pending":
            raise ValueError("Can only apply pending sync proposals")

        target_doc = await self._get_document(proposal.target_document_id, tenant_id)
        if not target_doc:
            raise ValueError("Target document not found")

        new_content = candidate_content or proposal.candidate_content
        if not new_content:
            raise ValueError("Candidate content is required")

        snapshot = DocumentVersion(
            tenant_id=tenant_id,
            document_id=target_doc.id,
            version=target_doc.version,
            content=target_doc.content,
            changes_summary=f"Before sync proposal {proposal.id}",
            created_by=decided_by,
        )
        self.db.add(snapshot)

        target_doc.content = new_content
        target_doc.version = target_doc.version + 1

        proposal.status = "applied"
        proposal.decided_by = decided_by
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.decision_note = decision_note
        proposal.result_document_version = target_doc.version

        if proposal.reference_id:
            reference = await self._get_document_reference(proposal.reference_id, tenant_id)
            if reference:
                reference.target_document_version = target_doc.version

        await self.db.flush()
        await self._resolve_analysis_if_complete(proposal.impact_analysis_id, tenant_id)
        await self.db.refresh(proposal)
        return proposal

    async def reject_sync_proposal(
        self,
        proposal_id: UUID,
        tenant_id: UUID,
        decided_by: UUID,
        decision_note: str | None = None,
    ) -> DocumentSyncProposal:
        """Reject a pending sync proposal without changing the target document."""
        proposal = await self._get_sync_proposal(proposal_id, tenant_id)
        if not proposal:
            raise ValueError("Sync proposal not found")
        if proposal.status != "pending":
            raise ValueError("Can only reject pending sync proposals")

        proposal.status = "rejected"
        proposal.decided_by = decided_by
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.decision_note = decision_note

        await self.db.flush()
        await self._resolve_analysis_if_complete(proposal.impact_analysis_id, tenant_id)
        await self.db.refresh(proposal)
        return proposal

    async def _get_sync_proposal(
        self,
        proposal_id: UUID,
        tenant_id: UUID,
    ) -> DocumentSyncProposal | None:
        result = await self.db.execute(
            select(DocumentSyncProposal).where(
                DocumentSyncProposal.id == proposal_id,
                DocumentSyncProposal.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_document_reference(
        self,
        reference_id: UUID,
        tenant_id: UUID,
    ) -> DocumentReference | None:
        result = await self.db.execute(
            select(DocumentReference).where(
                DocumentReference.id == reference_id,
                DocumentReference.tenant_id == tenant_id,
                DocumentReference.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def _collect_downstream_references(
        self,
        tenant_id: UUID,
        document_id: UUID,
        max_depth: int = 5,
    ) -> list[tuple[DocumentReference, Document, int]]:
        """Collect downstream references breadth-first, preserving target documents."""
        collected: list[tuple[DocumentReference, Document, int]] = []
        queue: list[tuple[UUID, int]] = [(document_id, 1)]
        visited_docs = {document_id}
        visited_refs: set[UUID] = set()

        while queue:
            current_doc_id, depth = queue.pop(0)
            if depth > max_depth:
                continue

            refs = await self.list_document_references(
                tenant_id=tenant_id,
                document_id=current_doc_id,
                direction="outgoing",
            )
            for reference in refs:
                if reference.id in visited_refs:
                    continue
                visited_refs.add(reference.id)
                target_doc = await self._get_document(reference.target_document_id, tenant_id)
                if not target_doc:
                    continue
                collected.append((reference, target_doc, depth))
                if target_doc.id not in visited_docs:
                    visited_docs.add(target_doc.id)
                    queue.append((target_doc.id, depth + 1))

        return collected

    def _build_sync_candidate(
        self,
        source_doc: Document,
        target_doc: Document,
        reference: DocumentReference,
    ) -> str:
        """Build conservative candidate content that preserves target text."""
        section = f"\n\n## Sync proposal from {source_doc.title} v{source_doc.version}\n"
        section += f"Reference: {reference.reference_type}\n"
        if reference.source_section or reference.target_section:
            section += (
                f"Sections: {reference.source_section or '-'} -> "
                f"{reference.target_section or '-'}\n"
            )
        section += "\n"
        section += source_doc.content.strip()
        base = target_doc.content.rstrip()
        return f"{base}{section}"

    def _impact_level_for_depth(self, depth: int) -> str:
        if depth <= 1:
            return "high"
        if depth == 2:
            return "medium"
        return "low"

    def _highest_impact_level(self, depths: list[int]) -> str:
        if not depths:
            return "low"
        if any(depth <= 1 for depth in depths):
            return "high"
        if any(depth == 2 for depth in depths):
            return "medium"
        return "low"

    async def _resolve_analysis_if_complete(
        self,
        analysis_id: UUID,
        tenant_id: UUID,
    ) -> None:
        result = await self.db.execute(
            select(DocumentSyncProposal).where(
                DocumentSyncProposal.impact_analysis_id == analysis_id,
                DocumentSyncProposal.tenant_id == tenant_id,
                DocumentSyncProposal.status == "pending",
            )
        )
        if result.scalars().first():
            return

        analysis = await self.get_document_impact_analysis(analysis_id, tenant_id)
        if analysis:
            analysis.status = "resolved"
            analysis.resolved_at = datetime.now(timezone.utc)
            await self.db.flush()

    async def generate_traceability_matrix(
        self,
        project_id: UUID,
        tenant_id: UUID,
        doc_type: str | None = None,
    ) -> list[TraceabilityMatrixItem]:
        """Generate requirement traceability matrix for a project.

        Args:
            project_id: Project UUID
            tenant_id: Tenant UUID
            doc_type: Optional document type filter

        Returns:
            List of traceability matrix items
        """
        # Get all documents for the project
        query = select(Document).where(
            Document.project_id == project_id,
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
        )

        if doc_type:
            query = query.where(Document.doc_type == doc_type)

        result = await self.db.execute(query.order_by(Document.doc_type, Document.title))
        documents = list(result.scalars().all())

        items = []
        for doc in documents:
            # Generate requirement ID from document type and title
            doc_type_prefix = {
                DocumentType.URS.value: "URS",
                DocumentType.BRD.value: "BRD",
                DocumentType.PRD.value: "PRD",
                DocumentType.USER_STORY.value: "US",
                DocumentType.DETAILED_DESIGN.value: "DD",
                DocumentType.INTERFACE.value: "IF",
                DocumentType.DATA_DICTIONARY.value: "DD",
                DocumentType.TEST_CASE.value: "TC",
            }.get(doc.doc_type, "DOC")

            # Extract requirement ID from title or generate one
            title_parts = doc.title.split()
            if title_parts and title_parts[0].replace("-", "").replace("_", "").isalnum():
                req_id = title_parts[0].upper()
            else:
                req_id = f"{doc_type_prefix}-{doc.id.hex[:8].upper()}"

            # Parse linked requirements from metadata
            linked_requirements = []
            if doc.metadata_json and isinstance(doc.metadata_json, dict):
                linked_requirements = doc.metadata_json.get("linked_requirements", [])
                if not isinstance(linked_requirements, list):
                    linked_requirements = []

            items.append(TraceabilityMatrixItem(
                requirement_id=req_id,
                requirement_title=doc.title,
                document_type=doc.doc_type,
                document_id=doc.id,
                document_version=doc.version,
                status=doc.status,
                linked_requirements=linked_requirements,
            ))

        return items

    async def get_impact_analysis(
        self,
        document_id: UUID,
        tenant_id: UUID,
    ) -> tuple[list[ImpactAnalysisItem], list[ImpactAnalysisItem]]:
        """Analyze impact of changes to a document.

        Determines which documents would be affected by changes to this document (downstream)
        and which documents this document depends on (upstream).

        Args:
            document_id: Document UUID
            tenant_id: Tenant UUID

        Returns:
            Tuple of (upstream_documents, downstream_documents)
        """
        # Get the source document
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        source_doc = result.scalar_one_or_none()
        if not source_doc:
            return [], []

        upstream = []
        downstream = []

        # Find documents where this document is in their linked requirements (upstream)
        upstream_result = await self.db.execute(
            select(Document).where(
                Document.project_id == source_doc.project_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        all_docs = list(upstream_result.scalars().all())

        for doc in all_docs:
            if doc.id == source_doc.id:
                continue

            # Check metadata for links
            is_upstream = False
            is_downstream = False

            if doc.metadata_json and isinstance(doc.metadata_json, dict):
                linked_docs = doc.metadata_json.get("linked_documents", [])
                if isinstance(linked_docs, list) and str(source_doc.id) in linked_docs:
                    is_upstream = True

                # Also check the reverse - does this doc link to source
                if doc.metadata_json.get("parent_document_id") == str(source_doc.id):
                    is_upstream = True

            # Check parent_document_id relationship
            if doc.parent_document_id == source_doc.id:
                is_upstream = True

            # Also check reverse links - source document's links
            if source_doc.metadata_json and isinstance(source_doc.metadata_json, dict):
                source_links = source_doc.metadata_json.get("linked_documents", [])
                if isinstance(source_links, list) and str(doc.id) in source_links:
                    is_downstream = True

            # Check if doc was created from this document (child)
            if source_doc.parent_document_id == doc.id:
                is_downstream = True

            if is_upstream:
                upstream.append(ImpactAnalysisItem(
                    document_id=doc.id,
                    document_type=doc.doc_type,
                    title=doc.title,
                    version=doc.version,
                    status=doc.status,
                    link_type="upstream",
                ))
            elif is_downstream:
                downstream.append(ImpactAnalysisItem(
                    document_id=doc.id,
                    document_type=doc.doc_type,
                    title=doc.title,
                    version=doc.version,
                    status=doc.status,
                    link_type="downstream",
                ))

        return upstream, downstream

    async def get_document_traceability(
        self,
        document_id: UUID,
        tenant_id: UUID,
    ) -> DocumentTraceabilityResponse | None:
        """Get full traceability lineage for a specific document.

        Args:
            document_id: Document UUID
            tenant_id: Tenant UUID

        Returns:
            DocumentTraceabilityResponse with ancestors, descendants, and linked documents
        """
        # Get the source document
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        source_doc = result.scalar_one_or_none()
        if not source_doc:
            return None

        # Build the document info
        doc_item = DocumentTraceabilityItem(
            id=source_doc.id,
            title=source_doc.title,
            doc_type=source_doc.doc_type,
            version=source_doc.version,
            status=source_doc.status,
        )

        # Get ancestors (documents that this document derives from)
        ancestors = []
        current_ancestor_id = source_doc.parent_document_id
        while current_ancestor_id:
            ancestor_result = await self.db.execute(
                select(Document).where(
                    Document.id == current_ancestor_id,
                    Document.tenant_id == tenant_id,
                    Document.deleted_at.is_(None),
                )
            )
            ancestor = ancestor_result.scalar_one_or_none()
            if not ancestor:
                break
            ancestors.append(DocumentTraceabilityItem(
                id=ancestor.id,
                title=ancestor.title,
                doc_type=ancestor.doc_type,
                version=ancestor.version,
                status=ancestor.status,
            ))
            current_ancestor_id = ancestor.parent_document_id

        # Get descendants (documents derived from this document via parent_document_id)
        descendants_result = await self.db.execute(
            select(Document).where(
                Document.parent_document_id == source_doc.id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        descendants = [
            DocumentTraceabilityItem(
                id=doc.id,
                title=doc.title,
                doc_type=doc.doc_type,
                version=doc.version,
                status=doc.status,
            )
            for doc in descendants_result.scalars().all()
        ]

        # Get linked documents from metadata
        linked = []
        if source_doc.metadata_json and isinstance(source_doc.metadata_json, dict):
            linked_ids = source_doc.metadata_json.get("linked_documents", [])
            if isinstance(linked_ids, list):
                for linked_id in linked_ids:
                    try:
                        linked_uuid = UUID(linked_id) if isinstance(linked_id, str) else linked_id
                        linked_doc_result = await self.db.execute(
                            select(Document).where(
                                Document.id == linked_uuid,
                                Document.tenant_id == tenant_id,
                                Document.deleted_at.is_(None),
                            )
                        )
                        linked_doc = linked_doc_result.scalar_one_or_none()
                        if linked_doc:
                            linked.append(DocumentTraceabilityItem(
                                id=linked_doc.id,
                                title=linked_doc.title,
                                doc_type=linked_doc.doc_type,
                                version=linked_doc.version,
                                status=linked_doc.status,
                            ))
                    except (ValueError, TypeError):
                        continue

        return DocumentTraceabilityResponse(
            document=doc_item,
            ancestors=ancestors,
            descendants=descendants,
            linked_documents=linked,
        )

    async def analyze_impact(
        self,
        change_request_id: UUID,
        tenant_id: UUID,
    ) -> tuple[list[ImpactAnalysisItem], list[ImpactAnalysisItem]]:
        """Analyze impact of a change request.

        Determines which documents would be affected by applying this change request.

        Args:
            change_request_id: Change request UUID
            tenant_id: Tenant UUID

        Returns:
            Tuple of (upstream_documents, downstream_documents)
        """
        # Get the change request
        result = await self.db.execute(
            select(ChangeRequest).where(
                ChangeRequest.id == change_request_id,
                ChangeRequest.tenant_id == tenant_id,
            )
        )
        change_request = result.scalar_one_or_none()
        if not change_request:
            return [], []

        # If the change request has a source document, analyze its impact
        if change_request.source_document_id:
            return await self.get_impact_analysis(
                document_id=change_request.source_document_id,
                tenant_id=tenant_id,
            )

        return [], []

    async def find_conflicts(
        self,
        document_id: UUID,
        tenant_id: UUID,
    ) -> ConflictAnalysisResponse:
        """Find contradictions between document versions.

        Analyzes a document and its linked documents to find conflicts,
        such as inconsistent links, missing parents, or content contradictions.

        Args:
            document_id: Document UUID
            tenant_id: Tenant UUID

        Returns:
            ConflictAnalysisResponse with list of conflicts
        """
        conflicts: list[ConflictItem] = []

        # Get the document
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        doc = result.scalar_one_or_none()
        if not doc:
            return ConflictAnalysisResponse(document_id=document_id, conflicts=[])

        # Check for missing parent conflict (document has no parent but has a doc_type that typically requires one)
        doc_type_hierarchy = {
            DocumentType.BRD.value: [DocumentType.URS.value],
            DocumentType.PRD.value: [DocumentType.BRD.value, DocumentType.URS.value],
            DocumentType.USER_STORY.value: [DocumentType.PRD.value, DocumentType.BRD.value, DocumentType.URS.value],
            DocumentType.DETAILED_DESIGN.value: [DocumentType.USER_STORY.value, DocumentType.PRD.value],
            DocumentType.TEST_CASE.value: [DocumentType.USER_STORY.value, DocumentType.DETAILED_DESIGN.value],
        }

        if doc.doc_type in doc_type_hierarchy and not doc.parent_document_id:
            # Check if there's actually a parent document that wasn't linked
            potential_parents = doc_type_hierarchy[doc.doc_type]
            parent_check = await self.db.execute(
                select(Document).where(
                    Document.project_id == doc.project_id,
                    Document.doc_type.in_(potential_parents),
                    Document.tenant_id == tenant_id,
                    Document.deleted_at.is_(None),
                )
            )
            existing_parents = list(parent_check.scalars().all())
            if existing_parents:
                conflicts.append(ConflictItem(
                    document_id=doc.id,
                    document_title=doc.title,
                    version_1=doc.version,
                    version_2=0,
                    conflict_type="missing_parent",
                    description=f"Document of type {doc.doc_type} is missing a parent link. Found {len(existing_parents)} potential parent(s).",
                    affected_entities=[],
                    rule_key="missing_parent",
                    severity="high",
                    evidence={
                        "candidate_parent_ids": sorted(str(parent.id) for parent in existing_parents),
                        "potential_parent_count": len(existing_parents),
                    },
                ))

        # Check for inconsistent links (document links to another doc that doesn't link back)
        if doc.metadata_json and isinstance(doc.metadata_json, dict):
            linked_ids = doc.metadata_json.get("linked_documents", [])
            if isinstance(linked_ids, list):
                for linked_id in linked_ids:
                    try:
                        linked_uuid = UUID(linked_id) if isinstance(linked_id, str) else linked_id
                        linked_result = await self.db.execute(
                            select(Document).where(
                                Document.id == linked_uuid,
                                Document.tenant_id == tenant_id,
                                Document.deleted_at.is_(None),
                            )
                        )
                        linked_doc = linked_result.scalar_one_or_none()
                        if not linked_doc:
                            conflicts.append(ConflictItem(
                                document_id=doc.id,
                                document_title=doc.title,
                                version_1=doc.version,
                                version_2=0,
                                conflict_type="inconsistent_link",
                                description=f"Document links to non-existent or deleted document: {linked_id}",
                                affected_entities=[],
                                rule_key="linked_document_missing",
                                severity="high",
                                related_document_id=linked_uuid,
                                evidence={"linked_document_id": str(linked_uuid)},
                            ))
                            continue

                        # Check if the linked document links back
                        if linked_doc.metadata_json and isinstance(linked_doc.metadata_json, dict):
                            back_links = linked_doc.metadata_json.get("linked_documents", [])
                            if str(doc.id) not in back_links:
                                conflicts.append(ConflictItem(
                                    document_id=doc.id,
                                    document_title=doc.title,
                                    version_1=doc.version,
                                    version_2=linked_doc.version,
                                    conflict_type="inconsistent_link",
                                    description=f"Document links to '{linked_doc.title}' but '{linked_doc.title}' does not link back",
                                    affected_entities=[],
                                    rule_key="missing_back_link",
                                    severity="medium",
                                    related_document_id=linked_doc.id,
                                    related_document_version=linked_doc.version,
                                    evidence={"linked_document_id": str(linked_doc.id)},
                                ))
                    except (ValueError, TypeError):
                        continue

        # Check for bidirectional link inconsistencies (parent_document_id vs metadata links)
        if doc.parent_document_id and doc.metadata_json and isinstance(doc.metadata_json, dict):
            metadata_parent = doc.metadata_json.get("parent_document_id")
            if metadata_parent and str(doc.parent_document_id) != str(metadata_parent):
                conflicts.append(ConflictItem(
                    document_id=doc.id,
                    document_title=doc.title,
                    version_1=doc.version,
                    version_2=doc.version,
                    conflict_type="inconsistent_link",
                    description="parent_document_id differs from metadata_json.parent_document_id",
                    affected_entities=[],
                    rule_key="parent_metadata_mismatch",
                    severity="high",
                    related_document_id=doc.parent_document_id,
                    evidence={
                        "metadata_parent_document_id": str(metadata_parent),
                        "parent_document_id": str(doc.parent_document_id),
                    },
                ))

        # Check child documents for inconsistent back-links
        children_result = await self.db.execute(
            select(Document).where(
                Document.parent_document_id == doc.id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        for child in children_result.scalars().all():
            if child.metadata_json and isinstance(child.metadata_json, dict):
                metadata_parent = child.metadata_json.get("parent_document_id")
                if metadata_parent and str(child.id) != str(metadata_parent):
                    # Not an error - the parent link is the authoritative source
                    pass

        return ConflictAnalysisResponse(document_id=document_id, conflicts=conflicts)

    async def find_project_conflicts(
        self,
        *,
        project_id: UUID,
        tenant_id: UUID,
    ) -> list[ConflictItem]:
        """Return all deterministic conflict findings for one project."""
        result = await self.db.execute(
            select(Document.id).where(
                Document.project_id == project_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        findings: list[ConflictItem] = []
        for document_id in result.scalars().all():
            analysis = await self.find_conflicts(document_id=document_id, tenant_id=tenant_id)
            findings.extend(analysis.conflicts)
        return findings

    async def generate_full_traceability_matrix(
        self,
        project_id: UUID,
        tenant_id: UUID,
    ) -> FullTraceabilityMatrixResponse:
        """Generate hierarchical traceability matrix.

        Creates a full matrix grouped by document type: URS -> BRD -> PRD -> User Story -> Test Case

        Args:
            project_id: Project UUID
            tenant_id: Tenant UUID

        Returns:
            FullTraceabilityMatrixResponse with documents grouped by type
        """
        # Get all documents for the project
        result = await self.db.execute(
            select(Document).where(
                Document.project_id == project_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            ).order_by(Document.doc_type, Document.title)
        )
        all_documents = list(result.scalars().all())

        # Group documents by type
        urs_items: list[TraceabilityMatrixItem] = []
        brd_items: list[TraceabilityMatrixItem] = []
        prd_items: list[TraceabilityMatrixItem] = []
        story_items: list[TraceabilityMatrixItem] = []
        test_items: list[TraceabilityMatrixItem] = []

        for doc in all_documents:
            # Generate requirement ID
            doc_type_prefix = {
                DocumentType.URS.value: "URS",
                DocumentType.BRD.value: "BRD",
                DocumentType.PRD.value: "PRD",
                DocumentType.USER_STORY.value: "US",
                DocumentType.DETAILED_DESIGN.value: "DD",
                DocumentType.INTERFACE.value: "IF",
                DocumentType.DATA_DICTIONARY.value: "DD",
                DocumentType.TEST_CASE.value: "TC",
            }.get(doc.doc_type, "DOC")

            title_parts = doc.title.split()
            if title_parts and title_parts[0].replace("-", "").replace("_", "").isalnum():
                req_id = title_parts[0].upper()
            else:
                req_id = f"{doc_type_prefix}-{doc.id.hex[:8].upper()}"

            # Get linked requirements from metadata
            linked_requirements = []
            if doc.metadata_json and isinstance(doc.metadata_json, dict):
                linked_requirements = doc.metadata_json.get("linked_requirements", [])
                if not isinstance(linked_requirements, list):
                    linked_requirements = []

            matrix_item = TraceabilityMatrixItem(
                requirement_id=req_id,
                requirement_title=doc.title,
                document_type=doc.doc_type,
                document_id=doc.id,
                document_version=doc.version,
                status=doc.status,
                linked_requirements=linked_requirements,
            )

            # Group by document type
            if doc.doc_type == DocumentType.URS.value:
                urs_items.append(matrix_item)
            elif doc.doc_type == DocumentType.BRD.value:
                brd_items.append(matrix_item)
            elif doc.doc_type == DocumentType.PRD.value:
                prd_items.append(matrix_item)
            elif doc.doc_type == DocumentType.USER_STORY.value:
                story_items.append(matrix_item)
            elif doc.doc_type == DocumentType.TEST_CASE.value:
                test_items.append(matrix_item)

        total = len(all_documents)
        return FullTraceabilityMatrixResponse(
            urs=urs_items,
            brd=brd_items,
            prd=prd_items,
            stories=story_items,
            tests=test_items,
            total=total,
        )


class ControlledBackwriteService:
    """Service for controlled document backwrite.

    Applies field patches by creating new document versions,
    never directly modifying existing baselines.
    """

    def __init__(self, db: AsyncSession):
        """Initialize controlled backwrite service.

        Args:
            db: Async database session
        """
        self.db = db

    async def backwrite_with_new_version(
        self,
        document_id: UUID,
        patches: list[FieldPatch],
        tenant_id: UUID,
        user_id: UUID,
    ) -> DocumentVersion:
        """Apply patches by creating new version.

        Creates a new DocumentVersion with the patched content,
        never directly modifying existing baselines.

        Args:
            document_id: Document UUID
            patches: List of field patches to apply
            tenant_id: Tenant UUID
            user_id: User ID applying the patches

        Returns:
            Created DocumentVersion

        Raises:
            ValueError: If document not found or patches invalid
        """
        # Get document
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        document = result.scalar_one_or_none()
        if not document:
            raise ValueError("Document not found")

        # Save current content as version
        old_version = DocumentVersion(
            tenant_id=tenant_id,
            document_id=document_id,
            version=document.version,
            content=document.content,
            changes_summary=f"Before backwrite - {len(patches)} patches",
            created_by=user_id,
        )
        self.db.add(old_version)

        # Apply patches to content
        content = document.content
        for patch in patches:
            if patch.patch_type == PatchType.REPLACE.value:
                content = self._apply_patch_to_content(content, patch.field_path, patch.new_value)
            elif patch.patch_type == PatchType.REMOVE.value:
                content = self._apply_patch_to_content(content, patch.field_path, None)
            elif patch.patch_type == PatchType.ADD.value:
                content = self._apply_patch_to_content(content, patch.field_path, patch.new_value)

        # Update document with new content and increment version
        document.content = content
        document.version = document.version + 1

        await self.db.flush()
        await self.db.refresh(document)
        return document

    def _apply_patch_to_content(
        self,
        content: str,
        field_path: str,
        new_value: str | None,
    ) -> str:
        """Apply a field patch to content string.

        This is a simplified implementation. In a real system, you might parse
        structured content (JSON, Markdown, etc.) and apply patches more precisely.

        Args:
            content: Original content
            field_path: Path to field (e.g., "sections.0.content")
            new_value: New value to set

        Returns:
            Patched content
        """
        # Try to parse as JSON for structured content
        try:
            data = json.loads(content)
            self._apply_json_patch(data, field_path, new_value)
            return json.dumps(data, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass

        # For plain text, apply field marker-based replacement
        # Supports multiple placeholder patterns:
        # - [field_name] or [field.name]
        # - {{field_name}} or {{field.name}}
        # - <field_name> or <field.name>
        if field_path and new_value is not None:
            result = content

            # Build list of possible marker variations from field_path
            # e.g., "sections.0.content" -> ["[sections.0.content]", "{{sections.0.content}}", etc.
            markers = self._build_field_markers(field_path)

            # Apply replacements for each marker pattern
            for marker in markers:
                if marker in result:
                    result = result.replace(marker, new_value)
                    break  # Only replace first matching marker

            # If no marker matched, try to find by simple field name at end of path
            if result == content:
                simple_name = field_path.split(".")[-1]
                simple_markers = [
                    f"[{simple_name}]",
                    f"{{{{{simple_name}}}}}",
                    f"<{simple_name}>",
                ]
                for marker in simple_markers:
                    if marker in result:
                        result = result.replace(marker, new_value)
                        break

            return result

        return content

    def _build_field_markers(self, field_path: str) -> list[str]:
        """Build list of possible placeholder markers from field path.

        Args:
            field_path: Dot-separated path (e.g., "sections.0.content")

        Returns:
            List of marker strings in various formats
        """
        markers = []

        # Full path markers
        markers.append(f"[{field_path}]")
        markers.append(f"{{{{{field_path}}}}}")
        markers.append(f"<{field_path}>")

        # Path with underscores/dashes
        path_underscore = field_path.replace(".", "_")
        path_dash = field_path.replace(".", "-")
        markers.append(f"[{path_underscore}]")
        markers.append(f"{{{{{path_underscore}}}}}")
        markers.append(f"[{path_dash}]")
        markers.append(f"{{{{{path_dash}}}}}")

        # Last component only
        simple_name = field_path.split(".")[-1]
        markers.append(f"[{simple_name}]")
        markers.append(f"{{{{{simple_name}}}}}")
        markers.append(f"<{simple_name}>")

        return markers

    def _apply_json_patch(
        self,
        data: dict | list,
        field_path: str,
        new_value: str | None,
    ) -> None:
        """Apply patch to JSON data structure.

        Args:
            data: JSON data (dict or list)
            field_path: Dot-separated path (e.g., "sections.0.content")
            new_value: New value to set
        """
        parts = field_path.split(".")
        current = data

        for i, part in enumerate(parts[:-1]):
            # Handle array indices
            if part.isdigit():
                idx = int(part)
                if isinstance(current, list) and idx < len(current):
                    current = current[idx]
                else:
                    return
            elif isinstance(current, dict):
                if part in current:
                    current = current[part]
                else:
                    return
            else:
                return

        # Set the final value
        final_key = parts[-1]
        if final_key.isdigit():
            idx = int(final_key)
            if isinstance(current, list) and idx < len(current):
                if new_value is not None:
                    current[idx] = new_value
                elif len(current) > idx:
                    del current[idx]
        elif isinstance(current, dict):
            if new_value is not None:
                current[final_key] = new_value
            elif final_key in current:
                del current[final_key]

    async def check_base_version_conflict(
        self,
        document_id: UUID,
        base_version_id: UUID,
        tenant_id: UUID,
    ) -> bool:
        """Check if there's a newer baseline than the base version.

        Returns True if a conflict exists (newer baseline found),
        False otherwise.

        Args:
            document_id: Document UUID
            base_version_id: Base version UUID to check against
            tenant_id: Tenant UUID

        Returns:
            True if conflict exists, False otherwise
        """
        # Get all baselines for this document
        result = await self.db.execute(
            select(DocumentBaseline).where(
                DocumentBaseline.document_id == document_id,
                DocumentBaseline.tenant_id == tenant_id,
            )
        )
        baselines = list(result.scalars().all())

        # Check if any baseline is based on a version newer than base_version_id
        for baseline in baselines:
            if baseline.version_id == base_version_id:
                continue
            # If baseline version_id is different and exists, we have a potential conflict
            # The baseline with version_id == base_version_id represents our base
            # Any baseline with a different version_id that was created after
            # our base represents a conflict
            return True

        return False

    async def apply_field_patch(
        self,
        patch_id: UUID,
        tenant_id: UUID,
    ) -> DocumentVersion | None:
        """Apply a single approved field patch to create new version.

        Args:
            patch_id: Field patch UUID
            tenant_id: Tenant UUID

        Returns:
            Created DocumentVersion or None if patch not found

        Raises:
            ValueError: If patch is not approved or not found
        """
        result = await self.db.execute(
            select(FieldPatch).where(
                FieldPatch.id == patch_id,
                FieldPatch.tenant_id == tenant_id,
            )
        )
        patch = result.scalar_one_or_none()
        if not patch:
            raise ValueError("Patch not found")

        if patch.status != PatchStatus.APPROVED.value:
            raise ValueError("Can only apply approved patches")
        if patch.reviewed_by is None:
            raise ValueError("Approved patch reviewer is required")

        # Get document
        doc_result = await self.db.execute(
            select(Document).where(
                Document.id == patch.document_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        document = doc_result.scalar_one_or_none()
        if not document:
            raise ValueError("Document not found")

        # Save current content as version snapshot
        old_version = DocumentVersion(
            tenant_id=tenant_id,
            document_id=document.id,
            version=document.version,
            content=document.content,
            changes_summary=f"Snapshot before patch {patch_id}",
            created_by=patch.reviewed_by,
        )
        self.db.add(old_version)

        # Apply patch
        content = self._apply_patch_to_content(
            document.content, patch.field_path, patch.new_value
        )

        # Update document
        document.content = content
        document.version = document.version + 1

        await self.db.flush()
        await self.db.refresh(document)

        # Return the new version (after increment)
        return old_version

    async def create_baseline_candidate(
        self,
        document_id: UUID,
        version_id: UUID,
        tenant_id: UUID,
        baseline_name: str,
        baseline_reason: str | None = None,
    ) -> DocumentBaseline:
        """Create a new baseline candidate for a document version.

        Args:
            document_id: Document UUID
            version_id: DocumentVersion UUID
            tenant_id: Tenant UUID
            baseline_name: Name for the baseline
            baseline_reason: Optional reason for creating baseline

        Returns:
            Created DocumentBaseline

        Raises:
            ValueError: If document or version not found
        """
        # Verify document exists
        doc_result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        document = doc_result.scalar_one_or_none()
        if not document:
            raise ValueError("Document not found")

        # Verify version exists
        ver_result = await self.db.execute(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id,
                DocumentVersion.tenant_id == tenant_id,
            )
        )
        version = ver_result.scalar_one_or_none()
        if not version:
            raise ValueError("Version not found")

        # Create baseline candidate
        baseline = DocumentBaseline(
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            baseline_name=baseline_name,
            baseline_reason=baseline_reason,
        )
        self.db.add(baseline)
        await self.db.flush()
        await self.db.refresh(baseline)
        return baseline

    async def backwrite_with_new_version(
        self,
        document_id: UUID,
        patches: list[FieldPatch],
        tenant_id: UUID,
        user_id: UUID,
        base_version_id: UUID | None = None,
        create_baseline_candidate_flag: bool = False,
    ) -> tuple[DocumentVersion, DocumentBaseline | None]:
        """Apply patches by creating new version with lineage tracking.

        Creates a new DocumentVersion with the patched content,
        never directly modifying existing baselines.

        Args:
            document_id: Document UUID
            patches: List of field patches to apply
            tenant_id: Tenant UUID
            user_id: User ID applying the patches
            base_version_id: Optional base version ID for conflict checking
            create_baseline_candidate_flag: Whether to create a baseline candidate

        Returns:
            Tuple of (created DocumentVersion, baseline if created)

        Raises:
            ValueError: If document not found, patches invalid, or conflict detected
        """
        # Check base version conflict if base_version_id provided
        if base_version_id:
            has_conflict = await self.check_base_version_conflict(
                document_id, base_version_id, tenant_id
            )
            if has_conflict:
                raise ValueError(
                    "Base version conflict detected: a newer baseline exists. "
                    "Cannot backwrite to an older base version."
                )

        # Get document
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        document = result.scalar_one_or_none()
        if not document:
            raise ValueError("Document not found")

        # Filter to only approved patches
        approved_patches = [p for p in patches if p.status == PatchStatus.APPROVED.value]
        if not approved_patches:
            raise ValueError("No approved patches to apply")

        # Save current content as version snapshot
        old_version = DocumentVersion(
            tenant_id=tenant_id,
            document_id=document_id,
            version=document.version,
            content=document.content,
            changes_summary=f"Before backwrite - {len(approved_patches)} patches",
            created_by=user_id,
        )
        self.db.add(old_version)

        # Apply patches to content
        content = document.content
        for patch in approved_patches:
            if patch.patch_type == PatchType.REPLACE.value:
                content = self._apply_patch_to_content(content, patch.field_path, patch.new_value)
            elif patch.patch_type == PatchType.REMOVE.value:
                content = self._apply_patch_to_content(content, patch.field_path, None)
            elif patch.patch_type == PatchType.ADD.value:
                content = self._apply_patch_to_content(content, patch.field_path, patch.new_value)

        # Update document with new content and increment version
        document.content = content
        document.version = document.version + 1

        await self.db.flush()
        await self.db.refresh(document)

        # Create new DocumentVersion record for the new state
        new_version = DocumentVersion(
            tenant_id=tenant_id,
            document_id=document_id,
            version=document.version,
            content=content,
            changes_summary=f"Backwrite with {len(approved_patches)} patches",
            created_by=user_id,
        )
        self.db.add(new_version)
        await self.db.flush()
        await self.db.refresh(new_version)

        # Create lineage record linking old version to new
        if base_version_id:
            lineage = LineageRecord(
                tenant_id=tenant_id,
                project_id=document.project_id,
                source_type="DocumentVersion",
                source_id=old_version.id,
                target_type="DocumentVersion",
                target_id=new_version.id,
                lineage_type=LineageType.DERIVED_FROM.value,
                metadata_json={"patches_applied": len(approved_patches)},
            )
            self.db.add(lineage)

        # Optionally create baseline candidate
        baseline = None
        if create_baseline_candidate_flag:
            baseline = DocumentBaseline(
                tenant_id=tenant_id,
                document_id=document_id,
                version_id=new_version.id,
                baseline_name=f"Backwrite v{document.version}",
                baseline_reason=f"Created from backwrite operation with {len(approved_patches)} patches",
            )
            self.db.add(baseline)
            await self.db.flush()
            await self.db.refresh(baseline)

        return new_version, baseline


class ChangeRequestCommentService:
    """Service for change request comments."""

    def __init__(self, db: AsyncSession):
        """Initialize comment service.

        Args:
            db: Async database session
        """
        self.db = db

    async def create_comment(
        self,
        change_request_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        content: str,
    ) -> ChangeRequestComment:
        """Create a comment on a change request.

        Args:
            change_request_id: Change request UUID
            tenant_id: Tenant UUID
            user_id: User UUID
            content: Comment content

        Returns:
            Created ChangeRequestComment
        """
        comment = ChangeRequestComment(
            tenant_id=tenant_id,
            change_request_id=change_request_id,
            user_id=user_id,
            content=content,
        )
        self.db.add(comment)
        await self.db.flush()
        await self.db.refresh(comment)
        return comment

    async def get_comments_for_change_request(
        self,
        change_request_id: UUID,
        tenant_id: UUID,
    ) -> list[ChangeRequestComment]:
        """Get all comments for a change request.

        Args:
            change_request_id: Change request UUID
            tenant_id: Tenant UUID

        Returns:
            List of ChangeRequestComments
        """
        result = await self.db.execute(
            select(ChangeRequestComment).where(
                ChangeRequestComment.change_request_id == change_request_id,
                ChangeRequestComment.tenant_id == tenant_id,
            ).order_by(ChangeRequestComment.created_at)
        )
        return list(result.scalars().all())
