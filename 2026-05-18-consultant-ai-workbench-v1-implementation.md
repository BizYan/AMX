# Consultant AI Workbench v1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full v1.0 consulting delivery AI workbench from `咨询交付 AI 工作台20260518.md` in the current directory without reusing old code.

**Architecture:** Use a modular Monorepo with FastAPI, Next.js, PostgreSQL/pgvector, Redis/ARQ, StorageProvider, VectorStoreProvider, SearchProvider, GraphStoreProvider, Provider Adapter boundaries, Contract-first DTOs, and strong tenant isolation. PostgreSQL is the transactional source of truth; Redis provides queue/cache/locks/rate limits; object storage holds non-structured files and large artifacts; pgvector is the default vector backend behind an abstraction. The plan is a construction sequence only; all v1.0 capabilities remain in scope.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, PostgreSQL + pgvector, Redis, ARQ, Next.js, React, TypeScript, Tailwind CSS, `@xyflow/react`, `elkjs`, Docker Compose, pytest, pnpm, uv.

---

## File Structure

```text
apps/
  api/
    app/
      api/
      core/
      db/
      domains/
      integrations/
      services/
      workers/
      main.py
    alembic/
    tests/
    Dockerfile
    pyproject.toml
  web/
    app/
    components/
    lib/
    package.json
    Dockerfile
  worker/
    Dockerfile
packages/
  contracts/
    openapi/
    schemas/
    events/
  shared/
infra/
  docker-compose.yml
  env.example
  scripts/
docs/
  superpowers/
```

## Task 1: Repository Foundation

**Files:**
- Create: `README.md`
- Create: `.gitignore`
- Create: `infra/env.example`
- Create: `infra/docker-compose.yml`
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/Dockerfile`
- Create: `apps/worker/Dockerfile`
- Create: `apps/web/package.json`
- Create: `apps/web/Dockerfile`

- [ ] Create the Monorepo directory structure.
- [ ] Add backend dependencies: FastAPI, uvicorn, SQLAlchemy, asyncpg, Alembic, Pydantic v2, passlib/bcrypt, python-jose, redis, arq, httpx, python-multipart, python-docx, python-pptx, openpyxl, pytest.
- [ ] Add frontend dependencies: Next.js, React, TypeScript, Tailwind, lucide-react, @xyflow/react, elkjs, zod, zustand.
- [ ] Add Docker Compose services: postgres with pgvector, redis, api, worker, web.
- [ ] Add `.env` example variables for MiniMax, bootstrap admin, JWT, database, Redis, storage backend, S3/OCI optional config, vector/search/graph provider mode.
- [ ] Verify: `docker compose -f infra/docker-compose.yml config`.

## Task 2: Backend Core, Settings, Database, Migrations

**Files:**
- Create: `apps/api/app/core/settings.py`
- Create: `apps/api/app/core/security.py`
- Create: `apps/api/app/db/session.py`
- Create: `apps/api/app/db/base.py`
- Create: `apps/api/app/db/bootstrap.py`
- Create: `apps/api/app/main.py`
- Create: `apps/api/alembic/env.py`
- Create: `apps/api/alembic/versions/0001_initial.py`
- Test: `apps/api/tests/test_bootstrap.py`

- [ ] Define typed settings using Pydantic v2 settings.
- [ ] Implement database engine/session lifecycle.
- [ ] Implement bcrypt password hashing and JWT creation/verification, with a Redis-cached + database-persisted JWT Blacklist (Redis as hot cache, DB as durable fallback; if Redis is unavailable the blacklist still works via DB lookup).
- [ ] Implement bootstrap admin creation from environment variables.
- [ ] Create initial Alembic migration with pgvector extension, tenant-scoped base columns, and partition-ready high-growth tables (`audit_logs`, `agent_events`, `metric_events`, `provider_runs`, `webhook_delivery_events`, `outbox_events`, `llm_prompt_cache_entries`).
- [ ] Add migration helpers or conventions for monthly/weekly partitions, retention policy metadata, and cold-archive markers for high-growth operational tables.
- [ ] Verify: `uv run pytest apps/api/tests/test_bootstrap.py -v`.

## Task 3: Identity, Tenant, RBAC, ABAC, Field Permissions, Audit

**Files:**
- Create: `apps/api/app/domains/identity/models.py`
- Create: `apps/api/app/domains/identity/schemas.py`
- Create: `apps/api/app/domains/identity/service.py`
- Create: `apps/api/app/domains/identity/router.py`
- Create: `apps/api/app/services/permission_evaluator.py`
- Create: `apps/api/app/services/audit_service.py`
- Test: `apps/api/tests/test_identity_permissions.py`

- [ ] Implement tenants, users, roles, project memberships, policies, field permission rules, audit logs.
- [ ] Implement login endpoint and current-user dependency.
- [ ] Enforce tenant-scoped queries using application-layer tenant_id filtering as primary isolation. Optionally enable PostgreSQL RLS per high-risk table as defense-in-depth (enabled per-table, not globally, after measuring query overhead).
- [ ] Enforce field-level deny/allow masking for API payloads.
- [ ] Write audit logs for login, permission changes, and sensitive reads/writes.
- [ ] Verify: `uv run pytest apps/api/tests/test_identity_permissions.py -v`.

## Task 4: Project Space and Source File Management

**Files:**
- Create: `apps/api/app/domains/projects/models.py`
- Create: `apps/api/app/domains/projects/schemas.py`
- Create: `apps/api/app/domains/projects/service.py`
- Create: `apps/api/app/domains/projects/router.py`
- Create: `apps/api/app/services/storage.py`
- Test: `apps/api/tests/test_projects_sources.py`

- [ ] Implement project CRUD, member management, project settings.
- [ ] Implement `StorageProvider` with local volume backend and S3/OCI-compatible configuration class.
- [ ] Implement source file upload metadata and file persistence.
- [ ] Store only metadata, hash, path, permission scope, version, and lineage in PostgreSQL; store uploaded files, Office files, exports, screenshots, and large RawArtifact attachments through `StorageProvider`.
- [ ] Enforce tenant/project permissions on source file access.
- [ ] Verify: `uv run pytest apps/api/tests/test_projects_sources.py -v`.

## Task 5: Provider Platform, LLM Gateway, Graphify/GitNexus Fixture Adapters

**Files:**
- Create: `apps/api/app/domains/providers/models.py`
- Create: `apps/api/app/domains/providers/contracts.py`
- Create: `apps/api/app/domains/providers/registry.py`
- Create: `apps/api/app/domains/providers/router.py`
- Create: `apps/api/app/integrations/llm/minimax_gateway.py`
- Create: `apps/api/app/integrations/graphify/adapter.py`
- Create: `apps/api/app/integrations/gitnexus/adapter.py`
- Create: `apps/api/app/services/graph_normalizer.py`
- Test: `apps/api/tests/contracts/test_provider_contracts.py`

- [ ] Implement Provider Registry, ProviderVersion, ProviderCapability, ProviderHealth, ProviderRun.
- [ ] Implement MiniMax OpenAI-compatible LLM Gateway using environment variables. Design the gateway with provider fallback routing so a second LLM provider can be added without changing call sites.
- [ ] Implement GraphifyProvider and GitNexusProvider real Adapter interfaces with fixture-backed execution.
- [ ] Persist RawArtifact metadata in PostgreSQL and large RawArtifact payloads/attachments through `StorageProvider`; persist normalized graph nodes/edges/citations with tenant/project/provider version metadata.
- [ ] Add contract tests: fixture JSON files covering Graphify and GitNexus happy paths and error paths, a replay script that verifies normalized output against fixture snapshots, and a schema validation step for each ProviderContract interface.
- [ ] Verify provider contract tests and fixture replay.

## Task 6: Knowledge, RAG, GraphRAG, Lineage

**Files:**
- Create: `apps/api/app/domains/knowledge/models.py`
- Create: `apps/api/app/domains/knowledge/schemas.py`
- Create: `apps/api/app/domains/knowledge/service.py`
- Create: `apps/api/app/domains/knowledge/router.py`
- Create: `apps/api/app/services/retrieval_service.py`
- Test: `apps/api/tests/test_knowledge_lineage.py`

- [ ] Implement KnowledgeEntry, KnowledgeLink, ProvenanceRecord, KnowledgeVector, LineageRecord.
- [ ] Implement knowledge ingestion from SourceFile and RawArtifact.
- [ ] Implement `VectorStoreProvider` with PostgreSQL pgvector as the default backend; business services must call retrieval abstractions rather than raw pgvector SQL.
- [ ] Implement `SearchProvider` with PostgreSQL FTS as the default backend for keyword/full-text retrieval, while preserving an extension point for OpenSearch/Elasticsearch.
- [ ] Implement `GraphStoreProvider` with PostgreSQL relationship tables as the default backend for KnowledgeLink, LineageRecord, impact analysis, and basic GraphRAG graph queries.
- [ ] Implement tenant/field permission filtering across vector retrieval, full-text search, graph queries, and generated Prompt context.
- [ ] Verify: `uv run pytest apps/api/tests/test_knowledge_lineage.py -v`.

## Task 7: Document Platform and Eight Core Document Types

**Files:**
- Create: `apps/api/app/domains/documents/models.py`
- Create: `apps/api/app/domains/documents/schemas.py`
- Create: `apps/api/app/domains/documents/document_types.py`
- Create: `apps/api/app/domains/documents/service.py`
- Create: `apps/api/app/domains/documents/router.py`
- Test: `apps/api/tests/test_documents_generation.py`

- [ ] Implement Document, DocumentEntity, DocumentVersion, DocumentBaseline, QualityResult.
- [ ] Implement URS, BRD, PRD, User Story, detailed design, interface document, data dictionary, test case schemas.
- [ ] Implement MiniMax-backed generation through LLM Gateway.
- [ ] Implement quality checks: required fields, consistency, MECE, source citation coverage.
- [ ] Verify full document chain generation against real service code.

## Task 8: Change Requests, Field Patches, Traceability Matrix, Controlled Backwrite

**Files:**
- Create: `apps/api/app/domains/change/models.py`
- Create: `apps/api/app/domains/change/schemas.py`
- Create: `apps/api/app/domains/change/service.py`
- Create: `apps/api/app/domains/change/router.py`
- Test: `apps/api/tests/test_change_backwrite.py`

- [ ] Implement ChangeRequest and FieldPatch lifecycle.
- [ ] Implement base version conflict checks.
- [ ] Implement controlled backwrite that creates a new DocumentVersion and new baseline candidate.
- [ ] Implement requirement traceability matrix generation.
- [ ] Verify stale version conflict and approved patch application.

## Task 9: Agent Runtime, Workflow DAG, Skills, Tools, ARQ Worker

**Files:**
- Create: `apps/api/app/domains/agent/models.py`
- Create: `apps/api/app/domains/agent/schemas.py`
- Create: `apps/api/app/domains/agent/service.py`
- Create: `apps/api/app/domains/agent/router.py`
- Create: `apps/api/app/workers/queue.py`
- Create: `apps/api/app/workers/jobs.py`
- Test: `apps/api/tests/test_agent_runtime.py`

- [ ] Implement WorkflowDefinition, WorkflowVersion (storing DAG as JSONB), AgentRun, AgentTask, AgentEvent, DLQ.
- [ ] Implement SkillContract and ToolContract validation.
- [ ] Implement ARQ job submission, retry, timeout, status updates, and dead-letter handling.
- [ ] Implement built-in skills: MECE, Issue Tree, 80/20, document review, export orchestration.
- [ ] Verify queued workflow execution and failure recovery.

## Task 10: Third-Party Integration Framework and Webhook/Outbox

**Files:**
- Create: `apps/api/app/domains/integrations/models.py`
- Create: `apps/api/app/domains/integrations/schemas.py`
- Create: `apps/api/app/domains/integrations/service.py`
- Create: `apps/api/app/domains/integrations/router.py`
- Create: `apps/api/app/workers/webhook_jobs.py`
- Test: `apps/api/tests/test_integrations_webhooks.py`

- [ ] Implement IntegrationProvider config by tenant.
- [ ] Implement unconfigured state without fake data.
- [ ] Implement WebhookSubscription, IntegrationInboundEvent, WebhookDeliveryEvent, OutboxEvent.
- [ ] Implement signature verification, idempotency, retries, and DLQ.
- [ ] Verify webhook delivery and unconfigured integration behavior.

## Task 11: Word, Markdown, PPTX Import/Export

**Files:**
- Create: `apps/api/app/domains/templates/models.py`
- Create: `apps/api/app/domains/templates/service.py`
- Create: `apps/api/app/domains/templates/router.py`
- Create: `apps/api/app/domains/export/models.py`
- Create: `apps/api/app/domains/export/service.py`
- Create: `apps/api/app/domains/export/router.py`
- Test: `apps/api/tests/test_export_office.py`

- [ ] Implement Template and TemplateVersion.
- [ ] Implement Word/Markdown export.
- [ ] Implement PPTX template parsing (strictly enforcing {{variable}} text placeholders), page type detection, content fill, and export validation.
- [ ] Persist ExportJob and ExportArtifact.
- [ ] Enforce field permission filtering before export.
- [ ] Verify generated files exist and are recorded.

## Task 12: Collaboration, Comments, Version Snapshots

**Files:**
- Create: `apps/api/app/domains/collaboration/models.py`
- Create: `apps/api/app/domains/collaboration/router.py`
- Create: `apps/api/app/services/collaboration_service.py`
- Test: `apps/api/tests/test_collaboration.py`

- [ ] Implement pessimistic module-level locking for v1.0 (known trade-off: CRDT real-time collaboration is deferred to v2.0 due to Python/Node.js ecosystem mismatch; this is the accepted downgrade).
- [ ] Persist collaboration state snapshots and comments.
- [ ] Remove WebSocket event fanout, replace with simple API lock endpoints.
- [ ] Write audit events for comments and version snapshots.
- [ ] Verify module-level locking and unlock timeouts.

## Task 13: Observability, Quota, Cache, Circuit Breaker, Reports

**Files:**
- Create: `apps/api/app/domains/ops/models.py`
- Create: `apps/api/app/domains/ops/router.py`
- Create: `apps/api/app/services/cache_service.py`
- Create: `apps/api/app/services/quota_service.py`
- Create: `apps/api/app/services/circuit_breaker.py`
- Create: `apps/api/app/services/report_service.py`
- Test: `apps/api/tests/test_ops_services.py`

- [ ] Implement metric events and health endpoints.
- [ ] Implement quota usage and rejection logic.
- [ ] Implement Redis cache and distributed lock helpers.
- [ ] Implement circuit breaker for LLM and Provider calls.
- [ ] Implement retention policy checks, partition health reporting, and cold-archive status for high-growth operational tables.
- [ ] Implement audit summary report and Excel export.
- [ ] Verify quota, cache, circuit breaker, and report tests.

## Task 14: Frontend Foundation and Typed Client

**Files:**
- Create: `apps/web/app/layout.tsx`
- Create: `apps/web/app/page.tsx`
- Create: `apps/web/lib/api-client.ts`
- Create: `apps/web/lib/auth.ts`
- Create: `apps/web/components/layout/app-shell.tsx`
- Create: `apps/web/components/ui/*`
- Test: `apps/web/tsconfig.json`

- [ ] Create Next.js app shell with authenticated navigation.
- [ ] Implement typed API client and token storage.
- [ ] Implement loading, empty, error, and permission states.
- [ ] Verify: `pnpm --dir apps/web typecheck`.

## Task 15: Frontend Pages

**Files:**
- Create pages under `apps/web/app/(app)/...`
- Create components under `apps/web/components/...`

- [ ] Implement login page.
- [ ] Implement dashboard, project space, upload/parse, document generation, document preview/review.
- [ ] Implement template center, knowledge page, traceability matrix, change request page.
- [ ] Implement workflow DAG editor using `@xyflow/react + elkjs`.
- [ ] Implement AgentOps, Provider Health, audit logs, quota/monitoring pages.
- [ ] Verify typecheck and critical page rendering.

## Task 16: End-to-End Verification and Deployment Readiness

**Files:**
- Create: `tests/e2e/README.md`
- Create: `infra/scripts/check-deploy.ps1`
- Modify: `README.md`

- [ ] Run Alembic migrations against Docker PostgreSQL.
- [ ] Start full Docker Compose stack.
- [ ] Verify admin bootstrap, login, project creation, upload through `StorageProvider`, document generation, knowledge ingestion, vector/search/graph retrieval, workflow run, export, audit and monitoring.
- [ ] Verify high-growth table partition creation, retention metadata, Redis cache/lock behavior, and object storage metadata/hash/path consistency.
- [ ] Run backend pytest suite.
- [ ] Run frontend typecheck/lint.
- [ ] Update README with OCI Ubuntu deployment commands.

## Self-Review

Spec coverage:
- Identity, tenant, RBAC/ABAC, audit: Task 3.
- Project and source files: Task 4.
- Provider Registry, MiniMax, Graphify/GitNexus fixture adapters: Task 5.
- Knowledge, RAG/GraphRAG, lineage: Task 6.
- Storage, vector/search/graph provider abstractions, and high-growth table partition governance: Tasks 2, 4, 6, 13, and 16.
- Eight document types and generation: Task 7.
- Change/backwrite/traceability: Task 8.
- Agent runtime and workflow: Task 9.
- Third-party integrations: Task 10.
- Word/PPTX export: Task 11.
- Realtime collaboration: Task 12.
- Monitoring, quota, cache, circuit breaker: Task 13.
- Frontend and DAG editor: Tasks 14-15.
- Docker Compose and OCI readiness: Tasks 1 and 16.

Placeholder scan:
- The plan intentionally contains no TODO/TBD entries.
- The only mock usage is the user-approved Graphify/GitNexus fixture Provider output.

Execution policy:
- Do not delete `咨询交付 AI 工作台20260518.md`.
- Do not commit or push unless the user explicitly asks.
- Do not write secrets into tracked files.
