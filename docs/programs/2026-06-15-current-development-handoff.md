# AMX Development Thread Handoff

Updated: 2026-06-15

## Program State

AMX is past the initial project-foundation stage. The product has real frontend, backend, persistence, CI, GitHub Release, OCI deployment, production health checks, authenticated smoke, rollback evidence, and GitNexus refresh. Future development should use mature-product domain Threads rather than one Thread for the whole project or one Thread per small PR.

Recommended Thread unit:

- one core product area or large business domain reaching its next maturity stage;
- normally 3-8 tightly related substantial PRs;
- related defects, discoverability, usability, and production acceptance;
- one or a small number of stage releases.

## Verified Repository And Production State

- Canonical local repository: `C:\amx\AMX-main`
- GitHub repository: `https://github.com/BizYan/AMX`
- Target branch: `main`
- Current `origin/main`: `dc918cfc581c8a526254ce94918bb6105ead07d6`
- Latest GitHub Release: `v0.6.2`
- OCI deployed SHA: `dc918cfc581c8a526254ce94918bb6105ead07d6`
- OCI deployed tag: `v0.6.2`
- Production health: `https://amx.yuanda.win/health` returned `{"status":"healthy","version":"1.0.0"}` on 2026-06-15.

## Active Work

### Ready To Merge

- PR #46: `infra: add evidence-driven continuous improvement loop`
- URL: `https://github.com/BizYan/AMX/pull/46`
- Branch: `infra/evidence-driven-continuous-improvement`
- Head SHA: `6fbf984bd02d3b48c99621f162ef5ab342d9a3f7`
- Status: mergeable; API, web build, deterministic E2E, Docker Compose, and collaboration-governance checks passed before this handoff update.
- Scope: continuous-improvement runbook, registry, deterministic validator, CI contract, and user-visible discoverability verification standard.

The next Thread must refresh PR #46 checks after this handoff commit, merge it when green, and apply release cadence rather than automatically deploying one governance PR.

## Durable Methods And Decisions

- Use `docs/runbooks/development-verification-standard.md` for risk-matched verification.
- Use `docs/runbooks/continuous-improvement.md` and `docs/continuous-improvement/registry.json` only for repeated, severe, or materially expensive problems.
- GitNexus is optional orientation and impact evidence, not a correctness proof or blocking dependency.
- Do not confuse merge, GitHub Release, production deployment, and production verification.
- Do not treat PowerShell console mojibake as source-code corruption without strict UTF-8 and rendered evidence.
- Verify user-visible capabilities through the normal entry path, not only by proving implementation existence.
- Do not use alternate proxy, GitHub profile, API-push, or worktree workarounds when the current Codex environment lacks network or full-access permissions. Ask the user to enable VPN TUN mode and Codex full access.

## Installed Local Skills

These Skills live under `C:\Users\dajid\.codex\skills` and are available across Threads:

- `project-foundation-release-orchestration`: early-stage version-train execution.
- `product-slice-release-orchestration`: mature-product domain execution.
- `pr-merge-release-deployment`: merge, release, deployment, verification, and rollback.
- `evidence-driven-process-improvement`: repeated-failure and process-improvement review.
- `unblock-codex-environment-access`: stop environment-specific workarounds and request TUN plus full access.
- `manage-development-thread-lifecycle`: select, continue, hand off, and close development Threads.

Skills preserve stable methods. This file and GitHub preserve dynamic project state.

## Rejected Or Deprecated Approaches

- Do not keep one Thread for the entire project lifetime.
- Do not create a Thread or PR for every minor field, copy, default tab, or isolated assertion.
- Do not default to multi-agent execution when coordination and review cost exceed implementation value.
- Do not run full local regression, full E2E, GitNexus analysis, or production deployment after every edit.
- Do not use mock or static-page existence as proof of a complete product capability.
- Do not rely on old chat history as the project source of truth.

## Next Thread Scope

Start one mature-product domain Thread. The first actions are:

1. Read this handoff, repository `AGENTS.md`, product specification, architecture, task inbox, and relevant domain state.
2. Refresh and merge PR #46 when all checks are green.
3. Reconstruct the product capability map from current code, production, open issues, and task sources.
4. Select one core product area that can reach its next maturity stage through 3-8 related substantial PRs.
5. Create `docs/programs/<domain>-maturity.md` before implementation and keep it current throughout the Thread.
6. Use `$product-slice-release-orchestration` for execution and `$pr-merge-release-deployment` only when release cadence or urgency requires it.

Do not begin with a minor isolated repair.
