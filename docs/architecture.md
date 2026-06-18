# AMX Architecture Baseline

## Purpose

Avenir Matrix is an AI-assisted consulting delivery platform. It combines project management, source files, generated documents, knowledge graph, change control, traceability, provider operations, and agent workflows in one controlled workspace.

This document is the shared architecture baseline for Codex, Antigravity, Claude, GitNexus, and human reviewers.

## System Components

```text
Browser
  -> Next.js web app
  -> FastAPI API
  -> PostgreSQL + pgvector
  -> Redis / ARQ worker
  -> file/export storage
  -> provider integrations
  -> OCI / Nginx / Docker Compose runtime
```

## Repository Layout

```text
apps/api     FastAPI backend, SQLAlchemy models, Alembic migrations, ARQ worker
apps/web     Next.js 14 frontend, app router, API client, E2E tests
infra        Docker Compose, Nginx, deployment, GitNexus, operational scripts
docs         architecture, runbooks, release notes, capability reports
tasks        task intake, task cards, GitNexus analysis records
packages     shared package boundary when needed
tests        repository-level tests and fixtures
```

## Backend Architecture

The API is organized by domains under `apps/api/app/domains`.

Core backend responsibilities:

- identity, tenants, users, roles, audit, JWT authentication;
- projects, project members, files, source files, and project lifecycle;
- documents, document generation, versioning, review workflow, comments;
- knowledge graph entries, links, graph query, and GraphRAG-facing structure;
- providers and provider tests with safe fallback behavior;
- operations metrics, quotas, circuit breakers, and usage statistics;
- agent workflows, workflow versions, workflow runs, and ARQ execution;
- exports, download jobs, and generated artifacts.

Provider config and provider version rows are not secret stores. They may hold
non-secret runtime metadata and `credential_ref` / `secret_ref` values only.
Runtime adapters may resolve those references from approved environment secrets
for a live candidate call, but resolved credentials must never be written back,
returned through APIs, logged, audited, exported, or uploaded as evidence.

Database schema is managed by Alembic. Runtime-only table creation should be treated as a compatibility fallback, not the preferred schema-management mechanism.

## Frontend Architecture

The web app uses Next.js app router under `apps/web/src/app`.

Core frontend responsibilities:

- public landing and login experience;
- authenticated dashboard shell;
- project list and project detail lifecycle pages;
- document list, generation, view, edit, workflow, comments, versions, export;
- knowledge graph and traceability views;
- settings for tenant, users, roles, API keys;
- providers, quotas, monitoring, agent operations, and workflows;
- consistent Chinese-first UI for production-facing pages.

All interactive controls must either perform an action, navigate, open a dialog, refresh data, or show a clear disabled state / toast explaining why the action is unavailable.

## Data And Workflow Boundaries

Project is the primary work container. Documents, files, source files, traceability links, knowledge entries, and generated artifacts should be scoped to a project and tenant where applicable.

Tenant is the operational boundary for users, roles, API keys, providers, quotas, and audit logs.

Provider readiness is an operational gate, not an exemption from the credential
boundary. Persisted raw credential fields such as `api_key`, `token`,
`access_token`, `secret`, or `service_key` are treated as unsafe configuration.

Document generation should preserve a traceable path from source material and prompt context to generated document, version, comments, workflow status, and export artifact.

## Runtime Environments

Local multi-agent development:

```text
C:\amx\AMX-main
C:\amx\AMX-codex
C:\amx\AMX-antigravity
C:\amx\AMX-claude
```

OCI runtime:

```text
/home/ubuntu/amx/production/AMX
/home/ubuntu/amx/staging
/home/ubuntu/amx/gitnexus
/home/ubuntu/amx/backups
/home/ubuntu/amx/logs
```

`/home/ubuntu/amx/production/ConsultantAIP` is a temporary compatibility
symlink only. `/home/ubuntu/ConsultantAIP` is retained as a second compatibility
alias. New deployment and operations automation must use the AMX path.

Production domain:

```text
https://amx.yuanda.win
```

## GitNexus Architecture Role

GitNexus is the shared code-fact and impact-analysis layer.

It should maintain:

- a main graph built from the protected main branch;
- optional PR graphs for feature branches;
- module, route, service, model, migration, and test relationships;
- query records included in task cards and PR descriptions.

GitNexus is internal infrastructure. It should not be exposed publicly unless protected by explicit authentication and network rules.

## Quality Gates

Baseline gates:

- API tests pass;
- web typecheck passes;
- web production build passes;
- Docker Compose config validates;
- frontend E2E or browser smoke tests pass for affected user flows;
- migration changes are tested on disposable data;
- PR includes GitNexus impact record or explicit unavailable fallback.

## Deployment Rules

Production deployment is Owner-approved only. Agents may prepare evidence,
publish documentation-only PRs within the governance rules, and operate the
approved GitHub Actions workflow, but product, API, security, migration, Docker,
workflow, release, deployment, and production changes require explicit Owner Go
before merge or promotion.

No release or production deployment may bypass:

- isolated candidate verification for the exact SHA;
- exact tag/SHA evidence;
- production health;
- authenticated production smoke;
- deployment provenance;
- candidate teardown evidence;
- rollback target verification.

A successful API candidate gate proves API runtime, migration-compatibility
baseline, authenticated smoke, isolation, and teardown for the verified SHA. It
must not be described as a full frontend or browser-based commercial-delivery
validation unless a real browser/user journey was separately verified.

Staging deployment may be triggered from PR branches when GitHub Environment secrets are configured.

Rollback must be possible by Git ref and Docker Compose restart.
