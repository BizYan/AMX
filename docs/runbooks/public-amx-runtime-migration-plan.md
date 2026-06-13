# Public AMX Runtime Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Public `BizYan/AMX`, `C:\amx\AMX-main`, `/home/ubuntu/amx/production/AMX`, and `/workspace/AMX` the canonical development, GitHub, OCI, and GitNexus identities while retaining a safe legacy OCI path alias.

**Architecture:** GitHub Actions remains the release authority and reads the canonical OCI path from the protected `production` Environment. A new idempotent OCI migration helper moves the existing production checkout to the AMX path and creates both old OCI paths as compatibility symlinks. Deployment, GitNexus, collaboration checks, current documentation, README examples, and active test labels use AMX names; historical reports and old local workspaces remain untouched.

**Tech Stack:** PowerShell, Bash, GitHub Actions, GitHub Environments, Git, Docker Compose, GitNexus, pytest.

---

### Task 1: Add Runtime Migration Contract

**Files:**
- Modify: `apps/api/tests/test_gitnexus_deploy_contract.py`
- Create: `infra/deploy/migrate-public-amx-runtime.sh`

- [x] Add assertions that the migration script uses `/home/ubuntu/amx/production/AMX`, preserves `/home/ubuntu/amx/production/ConsultantAIP` and `/home/ubuntu/ConsultantAIP` as symlinks, refuses conflicting real directories, and points the migrated checkout to `https://github.com/BizYan/AMX.git`.
- [x] Run `python -m pytest apps/api/tests/test_gitnexus_deploy_contract.py -q` and verify the new test fails because the migration helper is absent.
- [x] Implement an idempotent migration helper that validates paths, moves the legacy checkout only when necessary, creates the compatibility symlink, updates origin, and verifies the result.
- [x] Run the focused test and Bash syntax checks until they pass.

### Task 2: Make AMX Paths Canonical

**Files:**
- Modify: `infra/deploy/deploy-gitnexus.sh`
- Modify: `infra/scripts/check-agent-collaboration.sh`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/runbooks/oci-operations.md`
- Modify: `docs/runbooks/gitnexus-agent-protocol.md`
- Modify: `docs/runbooks/multi-agent-github-gitnexus-handbook.md`
- Modify: `infra/gitnexus/README.md`
- Modify: `apps/api/app/domains/agent/tools/web_search.py`
- Modify: active Playwright test titles under `apps/web/tests/e2e/playwright/`

- [x] Replace current runtime, operational, product, and test identifiers with AMX equivalents.
- [x] Preserve explicit legacy-path references only inside the migration helper and its compatibility documentation.
- [x] Run a scoped `rg` audit and verify remaining `ConsultantAIP` references are historical reports, legacy-workspace paths, or migration compatibility constants.

### Task 3: Publish And Merge

**Files:**
- Modify: `.github/pull_request_template.md` only if PR evidence commands need correction.

- [ ] Run focused pytest, Bash syntax, PowerShell parsing where relevant, `git diff --check`, Gitleaks commit scan, and the GitNexus change-record wrapper.
- [ ] Commit, push, and create a PR with risk, rollback, attribution, and GitNexus evidence.
- [ ] Wait for all required Public AMX checks and merge only after they pass.

### Task 4: Migrate OCI And Deploy

**External state:**
- GitHub `production` Environment secret `AMX_PRODUCTION_PATH`
- OCI production checkout and compatibility symlink

- [ ] Run the migration helper from the existing production checkout.
- [ ] Update `AMX_PRODUCTION_PATH` to `/home/ubuntu/amx/production/AMX` without printing secret values.
- [ ] Trigger and approve `Deploy production` from Public AMX `main`.
- [ ] Verify production health, authenticated smoke, deployment provenance, GitNexus health, GitNexus indexed SHA, canonical origin, and compatibility symlink.

### Task 5: Final Consistency Verification

- [ ] Verify local `C:\amx\AMX-main` is clean and tracks Public AMX main.
- [ ] Verify Public AMX has no open migration PR.
- [ ] Verify OCI production real path is `/home/ubuntu/amx/production/AMX`.
- [ ] Verify `/home/ubuntu/amx/production/ConsultantAIP` is a compatibility symlink to AMX.
- [ ] Verify `/home/ubuntu/ConsultantAIP` is a compatibility symlink to AMX.
- [ ] Verify GitNexus repository is `AMX` at `/workspace/AMX` and indexed at the deployed SHA.
- [ ] Record unresolved historical/private-workspace cleanup separately; do not delete it in this migration.
