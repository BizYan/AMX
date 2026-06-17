"""Project knowledge synchronization for external integrations."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.integrations.models import (
    IntegrationProjectBinding,
    IntegrationProvider,
    IntegrationSyncRun,
    IntegrationSyncedAsset,
)
from app.domains.integrations.schemas import (
    IntegrationNormalizedItem,
    IntegrationProjectBindingUpdate,
    IntegrationSyncPreviewResponse,
)
from app.domains.integrations.service import IntegrationService
from app.domains.knowledge.models import KnowledgeEntry, LineageRecord, ProvenanceRecord
from app.domains.knowledge.schemas import KnowledgeEntryUpdate
from app.domains.knowledge.service import KnowledgeService
from app.domains.projects.models import SourceFile, SourceFileStatus
from app.models.projects import Project


class IntegrationProjectSyncService:
    """Normalize external content and persist it as project knowledge."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_binding(
        self,
        *,
        tenant_id: UUID,
        integration_id: UUID,
        project_id: UUID,
        name: str,
        scope: dict[str, Any],
        field_mapping: dict[str, str],
        created_by: UUID,
        is_enabled: bool = True,
    ) -> IntegrationProjectBinding:
        integration = await self.db.scalar(
            select(IntegrationProvider).where(
                IntegrationProvider.id == integration_id,
                IntegrationProvider.tenant_id == tenant_id,
                IntegrationProvider.deleted_at.is_(None),
            )
        )
        project = await self.db.scalar(
            select(Project).where(
                Project.id == project_id,
                Project.tenant_id == tenant_id,
                Project.deleted_at.is_(None),
            )
        )
        if not integration:
            raise ValueError("Integration not found")
        if not project:
            raise ValueError("Project not found")
        binding = IntegrationProjectBinding(
            tenant_id=tenant_id,
            integration_provider_id=integration_id,
            project_id=project_id,
            name=name.strip(),
            scope_json=scope or {},
            field_mapping_json=field_mapping or {},
            cursor_json={},
            is_enabled=is_enabled,
            created_by=created_by,
        )
        self.db.add(binding)
        await self.db.flush()
        await self.db.refresh(binding)
        return binding

    async def list_bindings(
        self,
        integration_id: UUID,
        tenant_id: UUID,
    ) -> list[IntegrationProjectBinding]:
        result = await self.db.scalars(
            select(IntegrationProjectBinding)
            .where(
                IntegrationProjectBinding.integration_provider_id == integration_id,
                IntegrationProjectBinding.tenant_id == tenant_id,
                IntegrationProjectBinding.deleted_at.is_(None),
            )
            .order_by(IntegrationProjectBinding.created_at.desc())
        )
        return list(result.all())

    async def get_binding(
        self,
        binding_id: UUID,
        tenant_id: UUID,
    ) -> IntegrationProjectBinding | None:
        return await self.db.scalar(
            select(IntegrationProjectBinding)
            .options(selectinload(IntegrationProjectBinding.integration_provider))
            .where(
                IntegrationProjectBinding.id == binding_id,
                IntegrationProjectBinding.tenant_id == tenant_id,
                IntegrationProjectBinding.deleted_at.is_(None),
            )
        )

    async def update_binding(
        self,
        binding_id: UUID,
        tenant_id: UUID,
        updates: IntegrationProjectBindingUpdate,
    ) -> IntegrationProjectBinding | None:
        binding = await self.get_binding(binding_id, tenant_id)
        if not binding:
            return None
        if updates.name is not None:
            binding.name = updates.name.strip()
        if updates.scope is not None:
            binding.scope_json = updates.scope
        if updates.field_mapping is not None:
            binding.field_mapping_json = updates.field_mapping
        if updates.is_enabled is not None:
            binding.is_enabled = updates.is_enabled
        await self.db.flush()
        await self.db.refresh(binding)
        return binding

    async def preview_binding(
        self,
        binding_id: UUID,
        tenant_id: UUID,
        limit: int = 20,
    ) -> IntegrationSyncPreviewResponse:
        binding = await self._required_binding(binding_id, tenant_id)
        payload = await self._resolve_fetch(binding)
        items = self._normalize_payload(binding, payload)[:limit]
        return IntegrationSyncPreviewResponse(
            binding_id=binding.id,
            total=len(items),
            items=items,
            cursor=self._next_cursor(binding, items),
        )

    async def sync_binding(
        self,
        binding_id: UUID,
        tenant_id: UUID,
        requested_by: UUID | None,
    ) -> IntegrationSyncRun:
        binding = await self._required_binding(binding_id, tenant_id)
        run = IntegrationSyncRun(
            tenant_id=tenant_id,
            binding_id=binding.id,
            status="running",
            mode="sync",
            cursor_before_json=dict(binding.cursor_json or {}),
            cursor_after_json=dict(binding.cursor_json or {}),
            requested_by=requested_by,
            details_json={"binding_name": binding.name, "project_id": str(binding.project_id)},
        )
        self.db.add(run)
        await self.db.flush()

        if not binding.is_enabled:
            return await self._fail_run(run, binding, "Binding is disabled")

        try:
            payload = await self._resolve_fetch(binding)
            items = self._normalize_payload(binding, payload)
            run.total_count = len(items)
            item_errors: list[dict[str, str]] = []
            for item in items:
                try:
                    async with self.db.begin_nested():
                        outcome = await self._upsert_item(binding, run, item, requested_by)
                    if outcome == "created":
                        run.created_count += 1
                    elif outcome == "updated":
                        run.updated_count += 1
                    else:
                        run.unchanged_count += 1
                except Exception as exc:
                    run.failed_count += 1
                    item_errors.append({"external_id": item.external_id, "error": str(exc)})

            cursor = self._next_cursor(binding, items)
            run.cursor_after_json = cursor
            run.details_json = {**(run.details_json or {}), "item_errors": item_errors[:50]}
            run.status = "partial" if run.failed_count else "completed"
            run.error_message = f"{run.failed_count} item(s) failed" if run.failed_count else None
            run.completed_at = datetime.now(timezone.utc)
            binding.cursor_json = cursor
            binding.last_sync_status = run.status
            binding.last_synced_at = run.completed_at
            binding.last_error = run.error_message
            await self.db.flush()
            await self.db.refresh(run)
            return run
        except Exception as exc:
            return await self._fail_run(run, binding, str(exc))

    async def list_runs(
        self,
        binding_id: UUID,
        tenant_id: UUID,
        limit: int = 30,
    ) -> list[IntegrationSyncRun]:
        await self._required_binding(binding_id, tenant_id)
        result = await self.db.scalars(
            select(IntegrationSyncRun)
            .where(
                IntegrationSyncRun.binding_id == binding_id,
                IntegrationSyncRun.tenant_id == tenant_id,
            )
            .order_by(IntegrationSyncRun.created_at.desc())
            .limit(limit)
        )
        return list(result.all())

    async def retry_run(
        self,
        run_id: UUID,
        tenant_id: UUID,
        requested_by: UUID | None,
    ) -> IntegrationSyncRun:
        run = await self.db.scalar(
            select(IntegrationSyncRun).where(
                IntegrationSyncRun.id == run_id,
                IntegrationSyncRun.tenant_id == tenant_id,
            )
        )
        if not run:
            raise ValueError("Sync run not found")
        return await self.sync_binding(run.binding_id, tenant_id, requested_by)

    async def _required_binding(self, binding_id: UUID, tenant_id: UUID) -> IntegrationProjectBinding:
        binding = await self.get_binding(binding_id, tenant_id)
        if not binding:
            raise ValueError("Integration project binding not found")
        return binding

    async def _resolve_fetch(self, binding: IntegrationProjectBinding) -> Any:
        value = self._fetch_payload(binding)
        return await value if inspect.isawaitable(value) else value

    async def _fetch_payload(self, binding: IntegrationProjectBinding) -> Any:
        integration = binding.integration_provider
        config = integration.config_json or {}
        scope = binding.scope_json or {}
        helper = IntegrationService(self.db)
        sync_path = str(config.get("sync_path") or "").strip()
        binding_path = str(scope.get("path") or "").strip()
        if not sync_path and not binding_path:
            raise ValueError("Integration project sync source path is not configured. Set sync_path or scope.path before preview/sync.")

        endpoint = helper._build_endpoint(
            config,
            path_key="sync_path",
            fallback_path=binding_path or "/",
        )
        if binding_path:
            endpoint = helper._build_endpoint(
                {**config, "binding_path": binding_path},
                path_key="binding_path",
                fallback_path="/",
            )
        method = str(scope.get("method") or config.get("sync_method") or "GET").upper()
        params = dict(scope.get("params") or {})
        external_scope = scope.get("external_scope")
        if external_scope:
            default_scope_params = {
                "jira": "jql",
                "confluence": "spaceKey",
                "zentao": "projectID",
            }
            scope_param = str(
                scope.get("scope_param")
                or config.get("scope_param")
                or default_scope_params.get(integration.provider_type)
                or "scope"
            )
            params[scope_param] = external_scope
        cursor_param = scope.get("cursor_param")
        cursor_value = (binding.cursor_json or {}).get("updated_after")
        if cursor_param and cursor_value:
            params[str(cursor_param)] = cursor_value
        headers = helper._build_headers(config)
        timeout = float(config.get("timeout_seconds") or 30)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                response = await client.get(endpoint, headers=headers, params=params)
            else:
                response = await client.request(
                    method,
                    endpoint,
                    headers=headers,
                    json=scope.get("payload") or params,
                )
        response.raise_for_status()
        return response.json()

    def _normalize_payload(
        self,
        binding: IntegrationProjectBinding,
        payload: Any,
    ) -> list[IntegrationNormalizedItem]:
        scope = binding.scope_json or {}
        mapping = binding.field_mapping_json or {}
        raw_items = self._extract_items(payload, str(scope.get("item_path") or ""))
        normalized: list[IntegrationNormalizedItem] = []
        for index, raw in enumerate(raw_items):
            if not isinstance(raw, dict):
                raw = {"content": raw}
            external_id = self._field(raw, mapping.get("external_id"), ["external_id", "id", "key"])
            title = self._field(raw, mapping.get("title"), ["title", "summary", "name"])
            content = self._field(raw, mapping.get("content"), ["content", "description", "body", "text"])
            external_url = self._field(raw, mapping.get("external_url"), ["external_url", "url", "self"])
            updated_at = self._field(raw, mapping.get("updated_at"), ["updated_at", "updated", "modifiedDate"])
            external_id = str(external_id or f"item-{index + 1}").strip()
            title = str(title or external_id).strip()
            if isinstance(content, (dict, list)):
                content = json.dumps(content, ensure_ascii=False, sort_keys=True)
            content = str(content or title).strip()
            normalized.append(
                IntegrationNormalizedItem(
                    external_id=external_id,
                    title=title,
                    content=content,
                    external_url=str(external_url) if external_url else None,
                    external_updated_at=str(updated_at) if updated_at else None,
                    metadata={
                        "provider_type": binding.integration_provider.provider_type,
                        "binding_id": str(binding.id),
                        "raw_fields": sorted(raw.keys()),
                    },
                )
            )
        return normalized

    def _extract_items(self, payload: Any, item_path: str) -> list[Any]:
        if item_path:
            value = self._path(payload, item_path)
            if isinstance(value, list):
                return value
            if value is not None:
                return [value]
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("issues", "results", "items", "records", "pages", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
                if isinstance(value, dict):
                    nested = self._extract_items(value, "")
                    if nested:
                        return nested
            return [payload]
        return [payload]

    def _field(self, item: dict[str, Any], configured: str | None, defaults: list[str]) -> Any:
        for path in [configured, *defaults]:
            if not path:
                continue
            value = self._path(item, path)
            if value is not None:
                return value
        return None

    @staticmethod
    def _path(value: Any, path: str) -> Any:
        current = value
        for part in path.split("."):
            if not part:
                continue
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    async def _upsert_item(
        self,
        binding: IntegrationProjectBinding,
        run: IntegrationSyncRun,
        item: IntegrationNormalizedItem,
        requested_by: UUID | None,
    ) -> str:
        content_hash = hashlib.sha256(f"{item.title}\n{item.content}".encode("utf-8")).hexdigest()
        asset = await self.db.scalar(
            select(IntegrationSyncedAsset).where(
                IntegrationSyncedAsset.binding_id == binding.id,
                IntegrationSyncedAsset.external_id == item.external_id,
            )
        )
        metadata = {
            **item.metadata,
            "title": item.title,
            "summary": item.content[:240],
            "source": binding.integration_provider.name,
            "external_id": item.external_id,
            "external_url": item.external_url,
            "external_updated_at": item.external_updated_at,
            "integration_provider_id": str(binding.integration_provider_id),
            "sync_run_id": str(run.id),
        }
        if asset and asset.content_hash == content_hash:
            asset.external_updated_at = item.external_updated_at
            asset.external_url = item.external_url
            asset.metadata_json = metadata
            return "unchanged"

        knowledge = KnowledgeService(self.db)
        if asset:
            source_file = await self.db.get(SourceFile, asset.source_file_id)
            if source_file:
                source_file.hash = content_hash
                source_file.size = str(len(item.content.encode("utf-8")))
                source_file.metadata_json = metadata
                source_file.status = SourceFileStatus.READY.value
            await knowledge.update_entry(
                asset.knowledge_entry_id,
                binding.tenant_id,
                KnowledgeEntryUpdate(content=item.content, metadata=metadata),
            )
            asset.content_hash = content_hash
            asset.external_url = item.external_url
            asset.external_updated_at = item.external_updated_at
            asset.metadata_json = metadata
            return "updated"

        safe_name = re.sub(r"[^0-9A-Za-z._-]+", "-", item.external_id).strip("-") or "external-item"
        source_file = SourceFile(
            tenant_id=binding.tenant_id,
            project_id=binding.project_id,
            filename=f"{safe_name}.md",
            original_filename=f"{item.title}.md"[:255],
            content_type="text/markdown",
            size=str(len(item.content.encode("utf-8"))),
            hash=content_hash,
            storage_path=f"external://{binding.integration_provider_id}/{binding.id}/{item.external_id}",
            status=SourceFileStatus.READY.value,
            metadata_json=metadata,
        )
        self.db.add(source_file)
        await self.db.flush()
        entry = await knowledge.create_entry(
            tenant_id=binding.tenant_id,
            project_id=binding.project_id,
            entry_type="text",
            content=item.content,
            source_file_id=source_file.id,
            metadata=metadata,
            generate_embedding=False,
            created_by_id=requested_by,
        )
        self.db.add_all(
            [
                IntegrationSyncedAsset(
                    tenant_id=binding.tenant_id,
                    binding_id=binding.id,
                    external_id=item.external_id,
                    external_url=item.external_url,
                    external_updated_at=item.external_updated_at,
                    content_hash=content_hash,
                    source_file_id=source_file.id,
                    knowledge_entry_id=entry.id,
                    metadata_json=metadata,
                ),
                ProvenanceRecord(
                    tenant_id=binding.tenant_id,
                    project_id=binding.project_id,
                    entry_id=entry.id,
                    provider_id=f"integration:{binding.integration_provider.provider_type}",
                    provider_version_id=str(binding.integration_provider_id),
                    raw_artifact_id=item.external_id,
                    confidence=1.0,
                    normalization_notes=f"Imported through binding {binding.name}",
                ),
                LineageRecord(
                    tenant_id=binding.tenant_id,
                    project_id=binding.project_id,
                    source_type="integration_sync_run",
                    source_id=run.id,
                    target_type="knowledge_entry",
                    target_id=entry.id,
                    lineage_type="imports",
                    metadata_json={
                        "binding_id": str(binding.id),
                        "external_id": item.external_id,
                    },
                ),
            ]
        )
        await self.db.flush()
        return "created"

    @staticmethod
    def _next_cursor(
        binding: IntegrationProjectBinding,
        items: list[IntegrationNormalizedItem],
    ) -> dict[str, Any]:
        values = [item.external_updated_at for item in items if item.external_updated_at]
        return {
            **(binding.cursor_json or {}),
            "updated_after": max(values) if values else (binding.cursor_json or {}).get("updated_after"),
            "last_item_count": len(items),
        }

    async def _fail_run(
        self,
        run: IntegrationSyncRun,
        binding: IntegrationProjectBinding,
        message: str,
    ) -> IntegrationSyncRun:
        run.status = "failed"
        run.error_message = message[:2000]
        run.failed_count = max(run.failed_count, 1)
        run.completed_at = datetime.now(timezone.utc)
        binding.last_sync_status = "failed"
        binding.last_error = run.error_message
        await self.db.flush()
        await self.db.refresh(run)
        return run
