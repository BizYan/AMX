# Ops Release Evidence Console Design

## Goal

Promote the existing read-only Ops readiness dashboard into the authoritative runtime release-evidence console without adding mutable APIs, database state, or secret-bearing payloads.

## Evidence Sources

The service accepts only an allowlisted runtime contract. A sanitized JSON manifest named by `AMX_RELEASE_EVIDENCE_FILE` is the preferred source; existing `AMX_*` environment variables remain a fallback. Unknown manifest fields are ignored. The service never reads `.env` files and never returns raw manifest content.

The release evidence includes environment label, deployed ref and SHA, expected SHA, release tag, candidate verification run URL, production deployment run URL, authenticated smoke result and URL, GitNexus status and indexed SHA, and export timestamp.

## Status Model

- `blocked`: a recorded failed gate, SHA mismatch, failed provider/capability readiness, exhausted quota, or critical failure exists.
- `attention`: evidence is present but degraded, warning, or incomplete in a way that does not prove a failed gate.
- `not_recorded`: no meaningful release evidence is available.
- `ready`: required runtime identity, smoke, GitNexus, provider, capability, and quota evidence is recorded and consistent.

The response includes sanitized blocker codes and summaries so release documentation can reference one stable JSON payload.

## API And UI

`GET /api/v1/ops/readiness-dashboard` remains the dashboard snapshot. `GET /api/v1/ops/readiness-dashboard/evidence` returns the same sanitized release-evidence payload with a JSON attachment header. Both endpoints require the existing ops-reader permission and are read-only.

`/system-health` presents a “Release Evidence Console” section with overall status, environment, runtime and expected SHA, mismatch state, links to recorded workflow runs, smoke/provenance/GitNexus state, export timestamp, and latest blockers. The export button downloads from the dedicated endpoint.

## Security

Only explicit fields are parsed and returned. URLs must use HTTPS. SHA values must be full 40-character hexadecimal values. Secret-like keys and arbitrary payloads are never copied. Existing tenant-scoped operational aggregation remains unchanged.

## Verification

Backend tests cover source precedence, status calculation, SHA mismatch, missing evidence, endpoint read-only behavior, and redaction. Frontend typecheck/build and focused Playwright cover the console. Shell syntax and `git diff --check` complete the local gate.
