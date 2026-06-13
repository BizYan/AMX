# AMX Task System

All non-trivial work must be tracked through GitHub Issues or this `tasks/` directory.

Use this directory when a task is not yet ready for GitHub issue creation or when an agent needs a local handoff artifact.

## Required Flow

1. Add raw request to `tasks/inbox.md`.
2. Codex converts it into a task card from `tasks/templates/agent-task.md`.
3. Assigned agent creates a branch and records GitNexus query results.
4. Agent opens a PR with implementation evidence.
5. Claude and Codex review according to `AGENTS.md`.
6. Human owner decides merge and release.

## Naming

```text
tasks/task-YYYYMMDD-short-name.md
tasks/review-YYYYMMDD-pr-or-feature.md
tasks/incident-YYYYMMDD-short-name.md
```
