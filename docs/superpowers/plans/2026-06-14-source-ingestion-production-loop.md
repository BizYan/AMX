# Source Ingestion Production Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persistent, retryable, governed source-file ingestion loop from upload through knowledge availability and source deletion.

**Architecture:** Add a source-ingestion job model and service around the existing parsing executor. Upload routes enqueue jobs, explicit job routes execute and retry them, and source deletion/reingestion retires knowledge derived from the source.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Next.js, React Query, Playwright, pytest.

---

### Task 1: Persist and manage ingestion jobs

**Files:**
- Create: `apps/api/alembic/versions/0019_source_ingestion_jobs.py`
- Modify: `apps/api/app/domains/projects/models.py`
- Modify: `apps/api/app/domains/projects/schemas.py`
- Create: `apps/api/app/domains/projects/ingestion_service.py`
- Test: `apps/api/tests/domains/test_source_ingestion_jobs.py`

- [ ] Write failing tests proving task enqueue, active-task deduplication, successful execution, failed execution, and retry behavior.
- [ ] Run `python -m pytest apps/api/tests/domains/test_source_ingestion_jobs.py -q` and confirm failures are caused by missing contracts.
- [ ] Add the migration, job model, response schemas, and `SourceIngestionService`.
- [ ] Re-run the focused tests and confirm they pass.
- [ ] Commit the persistent ingestion job capability.

### Task 2: Govern reingestion and deletion

**Files:**
- Modify: `apps/api/app/domains/projects/ingestion_service.py`
- Modify: `apps/api/app/domains/projects/service.py`
- Test: `apps/api/tests/domains/test_source_ingestion_jobs.py`

- [ ] Write failing tests proving reingestion retires old source knowledge and source deletion retires source knowledge and links.
- [ ] Run the focused tests and confirm expected failures.
- [ ] Implement source-derived knowledge retirement and reusable reingestion.
- [ ] Re-run focused source-ingestion tests.
- [ ] Commit source knowledge governance.

### Task 3: Expose the API production loop

**Files:**
- Modify: `apps/api/app/domains/projects/router.py`
- Modify: `apps/api/tests/domains/test_project_files.py`
- Test: `apps/api/tests/domains/test_source_ingestion_jobs.py`

- [ ] Write failing router tests proving uploads enqueue rather than synchronously ingest and proving list/execute/retry/reingest endpoints.
- [ ] Run focused router tests and confirm expected failures.
- [ ] Implement the API routes and map service errors to HTTP responses.
- [ ] Run focused API, router-contract, and migration tests.
- [ ] Commit the API loop.

### Task 4: Complete the project-files user workflow

**Files:**
- Modify: `apps/web/src/lib/api-client.ts`
- Modify: `apps/web/src/app/(app)/projects/[projectId]/files/page.tsx`
- Modify: `apps/web/tests/e2e/playwright/fixtures/api-mocks.ts`
- Create: `apps/web/tests/e2e/playwright/source-ingestion-production-loop.spec.ts`

- [ ] Write failing E2E scenarios for queued task execution, failed-task retry, and completed-file reingestion.
- [ ] Run the focused Playwright spec and confirm expected failures.
- [ ] Add typed API client methods and task controls/status evidence to the project-files page.
- [ ] Run focused E2E, typecheck, and build.
- [ ] Commit the complete frontend workflow.

### Task 5: Prepare the PR

**Files:**
- Modify only files required by review findings.

- [ ] Run focused API tests, Alembic tests, web typecheck, production build, focused Playwright, and `git diff --check`.
- [ ] Run the GitNexus change-record wrapper once and record fallback limitations if needed.
- [ ] Review the diff for tenant isolation, duplicate active tasks, source knowledge retirement, and rollback coherence.
- [ ] Push the branch, create a PR with evidence, and watch CI to completion.
