# Ops Release Evidence Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver one sanitized, read-only runtime release-evidence contract and console.

**Architecture:** Extend the existing Ops readiness service with a typed release-evidence aggregate sourced from an allowlisted manifest or environment fallback. Reuse the existing authenticated ops route and `/system-health` page, adding one read-only export route and no persistence.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, Next.js/React Query, TypeScript, Playwright, pytest.

---

### Task 1: Release Evidence Contract

**Files:**
- Modify: `apps/api/app/domains/ops/schemas.py`
- Modify: `apps/api/app/domains/ops/readiness_dashboard.py`
- Test: `apps/api/tests/test_ops_readiness_dashboard.py`

- [x] Add failing tests for manifest allowlisting, environment fallback, SHA mismatch, ready, blocked, attention, not-recorded, and secret redaction.
- [x] Run `uv run --directory apps/api --extra dev python -m pytest tests/test_ops_readiness_dashboard.py -q` and confirm the new assertions fail because the contract is absent.
- [x] Add typed release-evidence schemas, safe manifest parsing, status calculation, and blocker generation.
- [x] Rerun the focused backend test and confirm it passes.

### Task 2: Read-Only Evidence Export

**Files:**
- Modify: `apps/api/app/domains/ops/router.py`
- Test: `apps/api/tests/test_ops_readiness_dashboard.py`

- [x] Add a failing route contract test requiring `GET /ops/readiness-dashboard/evidence`, ops-reader authorization, JSON content, and no mutation method.
- [x] Run the focused test and confirm a 404 or missing route failure.
- [x] Add the read-only route using the existing service and an attachment response header.
- [x] Rerun the focused test and confirm it passes.

### Task 3: Release Evidence Console UI

**Files:**
- Modify: `apps/web/src/lib/api-client.ts`
- Modify: `apps/web/src/app/(app)/health/page.tsx`
- Modify: `apps/web/tests/e2e/playwright/fixtures/mock-data.ts`
- Modify: `apps/web/tests/e2e/playwright/ops-readiness-dashboard.spec.ts`

- [x] Add failing Playwright assertions for the console title, status, environment, runtime/expected SHA, mismatch indicator, workflow links, smoke/provenance/GitNexus, export timestamp, blockers, and absence of secret-bearing text.
- [x] Run the focused Playwright spec and confirm the new assertions fail.
- [x] Add typed client contracts and render the console using the existing query without additional waterfalls.
- [x] Add an authenticated JSON export call and update deterministic fixture data.
- [x] Run the focused Playwright spec and confirm it passes.

### Task 4: Final Verification And PR

**Files:**
- Modify only files already listed when fixing proven failures.

- [x] Run focused backend tests.
- [x] Run `pnpm --dir apps/web typecheck` and `pnpm --dir apps/web build` sequentially.
- [x] Run the focused Playwright spec.
- [x] Run `bash -n infra/deploy/authenticated-smoke.sh` and `git diff --check`.
- [x] Generate one GitNexus impact record or record fallback evidence.
- [x] Commit, push, open one PR, wait for checks once, and merge only after all gates and Owner Go.
