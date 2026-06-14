"""Persistent source ingestion job orchestration."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.knowledge.models import KnowledgeEntry, KnowledgeLink
from app.domains.projects.models import SourceFile, SourceFileStatus, SourceIngestionJob
from app.domains.projects.service import SourceFileService


class SourceIngestionError(ValueError):
    """Raised when an ingestion lifecycle transition is invalid."""


class SourceIngestionService:
    """Coordinates durable source-ingestion jobs and derived knowledge."""

    ACTIVE_STATUSES = ("pending", "running")

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_job(self, job_id: UUID, tenant_id: UUID | None = None) -> SourceIngestionJob | None:
        query = select(SourceIngestionJob).where(SourceIngestionJob.id == job_id)
        if tenant_id is not None:
            query = query.where(SourceIngestionJob.tenant_id == tenant_id)
        return (await self.db.execute(query)).scalar_one_or_none()

    async def list_jobs(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        source_file_id: UUID | None = None,
    ) -> list[SourceIngestionJob]:
        query = select(SourceIngestionJob).where(
            SourceIngestionJob.project_id == project_id,
            SourceIngestionJob.tenant_id == tenant_id,
        )
        if source_file_id is not None:
            query = query.where(SourceIngestionJob.source_file_id == source_file_id)
        result = await self.db.execute(query.order_by(SourceIngestionJob.created_at.desc()))
        return list(result.scalars().all())

    async def enqueue(self, source_file: SourceFile, requested_by_id: UUID | None) -> SourceIngestionJob:
        active = (
            await self.db.execute(
                select(SourceIngestionJob)
                .where(
                    SourceIngestionJob.source_file_id == source_file.id,
                    SourceIngestionJob.status.in_(self.ACTIVE_STATUSES),
                )
                .order_by(SourceIngestionJob.created_at.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if active:
            return active

        source_file.status = SourceFileStatus.PENDING.value
        source_file.metadata_json = {
            **(source_file.metadata_json or {}),
            "ingestionStage": "queued",
            "ingestionSummary": "资料已进入知识摄取队列。",
            "requiredAction": None,
            "errorMessage": None,
        }
        job = SourceIngestionJob(
            tenant_id=source_file.tenant_id,
            project_id=source_file.project_id,
            source_file_id=source_file.id,
            requested_by_id=requested_by_id,
            status="pending",
            stage="queued",
            result_json={},
        )
        self.db.add(job)
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def execute(
        self,
        job_id: UUID,
        *,
        tenant_id: UUID | None = None,
        storage=None,
    ) -> SourceIngestionJob:
        job = await self.get_job(job_id, tenant_id)
        if not job:
            raise SourceIngestionError("ingestion job not found")
        if job.status not in self.ACTIVE_STATUSES:
            raise SourceIngestionError(f"{job.status} ingestion job cannot be executed")
        if job.attempt_count >= job.max_attempts:
            raise SourceIngestionError("ingestion job exceeded its retry limit")

        job.status = "running"
        job.stage = "extracting_knowledge"
        job.attempt_count += 1
        job.started_at = datetime.now(timezone.utc)
        job.completed_at = None
        job.error_message = None
        await self.db.flush()

        source_file = await SourceFileService(self.db).get_source_file(job.source_file_id, job.tenant_id)
        if not source_file:
            job.status = "failed"
            job.stage = "source_unavailable"
            job.error_message = "source file not found"
            job.completed_at = datetime.now(timezone.utc)
            await self.db.flush()
            return job

        entries = await SourceFileService(self.db).ingest_source_file(
            source_file.id,
            job.tenant_id,
            job.project_id,
            storage=storage,
        )
        job.completed_at = datetime.now(timezone.utc)
        if source_file.status == SourceFileStatus.READY.value:
            job.status = "completed"
            job.stage = "knowledge_ready"
            job.result_json = {
                "knowledge_entry_count": len(entries),
                "knowledge_link_count": (source_file.metadata_json or {}).get("knowledgeLinkCount", 0),
            }
        else:
            job.status = "failed"
            job.stage = "ingestion_failed"
            job.error_message = (source_file.metadata_json or {}).get("errorMessage") or "source ingestion failed"
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def retry(self, job_id: UUID, requested_by_id: UUID | None) -> SourceIngestionJob:
        job = await self.get_job(job_id)
        if not job:
            raise SourceIngestionError("ingestion job not found")
        if job.status != "failed":
            raise SourceIngestionError(f"{job.status} ingestion job cannot be retried")
        if job.attempt_count >= job.max_attempts:
            raise SourceIngestionError("ingestion job exceeded its retry limit")

        job.status = "pending"
        job.stage = "queued_for_retry"
        job.requested_by_id = requested_by_id
        job.error_message = None
        job.started_at = None
        job.completed_at = None
        source_file = await SourceFileService(self.db).get_source_file(job.source_file_id, job.tenant_id)
        if source_file:
            source_file.status = SourceFileStatus.PENDING.value
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def retire_source_knowledge(self, source_file_id: UUID, tenant_id: UUID) -> int:
        now = datetime.now(timezone.utc)
        active_jobs = list(
            (
                await self.db.scalars(
                    select(SourceIngestionJob).where(
                        SourceIngestionJob.source_file_id == source_file_id,
                        SourceIngestionJob.tenant_id == tenant_id,
                        SourceIngestionJob.status.in_(self.ACTIVE_STATUSES),
                    )
                )
            ).all()
        )
        for job in active_jobs:
            job.status = "cancelled"
            job.stage = "source_retired"
            job.completed_at = now
        entries = list(
            (
                await self.db.scalars(
                    select(KnowledgeEntry).where(
                        KnowledgeEntry.source_file_id == source_file_id,
                        KnowledgeEntry.tenant_id == tenant_id,
                        KnowledgeEntry.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        entry_ids = [entry.id for entry in entries]
        for entry in entries:
            entry.deleted_at = now
        if entry_ids:
            links = list(
                (
                    await self.db.scalars(
                        select(KnowledgeLink).where(
                            KnowledgeLink.tenant_id == tenant_id,
                            KnowledgeLink.deleted_at.is_(None),
                            or_(
                                KnowledgeLink.source_entry_id.in_(entry_ids),
                                KnowledgeLink.target_entry_id.in_(entry_ids),
                            ),
                        )
                    )
                ).all()
            )
            for link in links:
                link.deleted_at = now
        await self.db.flush()
        return len(entries)

    async def reingest(
        self,
        source_file_id: UUID,
        tenant_id: UUID,
        project_id: UUID,
        requested_by_id: UUID | None,
    ) -> SourceIngestionJob:
        source_file = await SourceFileService(self.db).get_source_file(source_file_id, tenant_id)
        if not source_file or source_file.project_id != project_id:
            raise SourceIngestionError("source file not found")
        active = (
            await self.db.execute(
                select(SourceIngestionJob).where(
                    SourceIngestionJob.source_file_id == source_file_id,
                    SourceIngestionJob.status.in_(self.ACTIVE_STATUSES),
                ).order_by(SourceIngestionJob.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if active:
            raise SourceIngestionError("source file already has an active ingestion job")

        retired_count = await self.retire_source_knowledge(source_file_id, tenant_id)
        source_file.status = SourceFileStatus.PENDING.value
        source_file.metadata_json = {
            **(source_file.metadata_json or {}),
            "extractedKnowledgeCount": 0,
            "knowledgeLinkCount": 0,
            "retiredKnowledgeCount": retired_count,
            "requiredAction": None,
            "errorMessage": None,
        }
        return await self.enqueue(source_file, requested_by_id)
