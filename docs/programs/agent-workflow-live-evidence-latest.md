# Agent Workflow Live Evidence Latest

Date: 2026-06-21

Status: blocked before live provider/tool evidence. This document records the
latest execution boundary for converting Agent Workflow Runtime from synthetic
interaction evidence to a real candidate/staging provider or tool interaction
proof. It is not a live provider/tool readiness claim.

## Target

- Target environment: not selected.
- Approved SHA under review:
  `6f597c41c8054c15fe3afe9dcf252518fc4edd22`
- Latest verified production remains `v1.0.15` /
  `3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9`.

No candidate or staging runtime endpoint was available in the local execution
boundary.

## Required Inputs

The live evidence task requires all of:

- candidate or staging runtime running;
- safe non-production provider/tool credential available through
  `credential_ref` or `secret_ref`;
- Owner-selected bounded workflow that is safe to execute;
- authenticated runtime user for API and Agent Ops UI validation.

Local input status:

| Input | Status |
| --- | --- |
| `AGENT_LIVE_EVIDENCE_TARGET` | Missing |
| `E2E_WEB_URL` | Missing |
| `E2E_API_URL` | Missing |
| `E2E_USER_EMAIL` | Missing |
| `E2E_PASSWORD` | Missing |
| `AMX_AGENT_TOOL_SECRET_REF` | Missing |
| `AMX_AGENT_PROVIDER_SECRET_REF` | Missing |
| `AMX_CANDIDATE_LLM_API_KEY` / `RELEASE_CANDIDATE_LLM_API_KEY` | Missing |

No raw credential was accessed, printed, stored, or requested.

## Existing Non-Live Evidence

Existing repository coverage still proves the synthetic and contract boundary:

- DAG validation, immutable workflow version binding, input snapshot, task and
  event persistence;
- provider/tool interaction references through sanitized artifact or event
  refs;
- `credential_boundary=secret_ref_only`;
- failed task/event evidence;
- retry evidence linked to prior failure;
- cancel behavior preventing further task execution;
- Agent Ops UI display of run status, task timeline, retry/cancel controls,
  provider/tool summaries, evidence refs, and redaction boundary.

These checks do not prove a real candidate/staging provider or tool call.

## Verification Completed

Backend:

```text
uv run --directory apps/api --extra dev python -m pytest tests/test_agent_workflow_runtime.py tests/test_agent_runtime_production_loop.py -q
32 passed
```

Frontend:

```text
pnpm --dir apps/web build
pnpm --dir apps/web typecheck
```

Both passed after clearing stale local `.next` state and running the checks
sequentially.

Focused Agent Ops Playwright:

```text
pnpm --dir apps/web exec playwright test tests/e2e/playwright/agent-orchestration.spec.ts --grep "agent ops" --reporter=list
7 passed
```

## Live Evidence Not Produced

No live evidence was produced for:

- workflow ID;
- workflow version ID;
- run ID;
- task IDs;
- real provider/tool interaction evidence refs;
- retry/cancel evidence from a live candidate/staging execution;
- Agent Ops UI screenshot or Playwright artifact against a real runtime.

## Required Next Action

Owner must select one bounded candidate/staging workflow and provide an approved
non-production credential boundary through `credential_ref` or `secret_ref`.

After the runtime and inputs exist, rerun the live workflow through the API,
verify Agent Ops UI against the same run, and replace this blocked evidence
boundary with sanitized live evidence containing workflow/run/task IDs,
interaction refs, retry/cancel evidence, redaction checks, and artifact paths.
