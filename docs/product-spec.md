# Avenir Matrix Product Specification

## Product Name

Avenir Matrix

## Product Positioning

Avenir Matrix is a human-in-the-loop AI delivery engine for senior consultants, solution architects, and delivery teams. It helps teams collect project material, structure knowledge, generate professional documents, track changes, and audit delivery lineage.

## Primary Users

### Tenant Administrator

Configures tenant settings, manages users, roles, API keys, providers, quotas, and operational visibility.

### Project Lead

Creates projects, uploads source material, invites members, monitors project progress, reviews generated documents, and controls delivery status.

### Consultant / Architect

Uses project files, knowledge graph, templates, and AI generation to produce URS, BRD, PRD, design specifications, test cases, and related consulting deliverables.

### Reviewer / Approver

Reviews document workflow state, comments, versions, traceability, changes, and approval actions.

### Operations / Platform Owner

Monitors health, quotas, providers, agent workflows, exports, and production reliability.

## Core Capabilities

Current implemented capability areas:

- authentication and current user session;
- tenant, user, role, API key management;
- project creation, listing, member invitation, and archive state;
- project files and upload entry points;
- document generation, document list, document detail, comments, versions, export entry points;
- source files and knowledge graph entry points;
- traceability, change workflow, and audit-oriented views;
- provider management and provider connection test fallback;
- operations health, quotas, usage, rate limits, and circuit breaker views;
- agent workflows and workflow run entry points;
- OCI deployment and GitHub-governed release operations.

## UX Requirements

The production UI is Chinese-first. English may remain only for protocol names, model names, file extensions, API identifiers, and developer-only logs.

All pages must avoid:

- white screen / client-side exception;
- hidden overlay intercepting clicks;
- controls that silently do nothing;
- unreadable dark-mode text;
- 404 navigation from visible product links;
- generated documents with empty detail view;
- upload controls without progress or user feedback.

## Document Generation Requirements

A document generation flow should:

1. require project context;
2. allow selecting a document type;
3. accept user requirements and supporting context;
4. create a persisted document;
5. make the document visible in project and global document lists;
6. allow viewing generated content;
7. preserve version, workflow, comments, and export paths where available.

## Traceability Requirements

Traceability should connect source files, generated documents, knowledge entries, changes, and review artifacts. It should support impact analysis and audit narratives for high-value consulting deliverables.

## Operations Requirements

Operations pages must distinguish:

- system health;
- tenant quota;
- provider state;
- circuit breaker state;
- usage statistics;
- agent workflow execution state;
- export job state.

Raw API health JSON should not be the authenticated product health page.

## Non-Goals

The system does not give agents autonomous production release authority.
Product, API, security, migration, Docker, workflow, release, deployment, and
production changes require explicit Owner Go before merge or promotion.

Low-risk documentation-only PRs may be auto-merged after required checks pass
when they do not change product behavior, API behavior, security posture,
migrations, Docker/runtime configuration, workflows, release behavior,
deployment behavior, or production state.

Release-candidate API verification is not a full frontend commercial-delivery
validation. It may support Owner Go only for the exact verified SHA and only
when the report clearly states the API runtime scope, migration-compatibility
scope, isolation, teardown, health, authenticated smoke, provenance, and
rollback evidence.

GitNexus does not replace tests, CI, review, or user acceptance.

Mock-only UI behavior should not be treated as complete product capability.
