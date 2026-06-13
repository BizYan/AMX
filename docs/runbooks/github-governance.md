# GitHub Governance Runbook

## Branch Model

- `main`: production-ready branch. Only merge through reviewed PRs.
- `feature/v0.x.0`: version development branch for a release train.
- `feature/v0.x.0-*`: agent or human task branches.
- `release/v0.x.0`: release stabilization branch.
- `hotfix/v0.x.y`: urgent production fix branch.

## Required Repository Settings

Enable branch protection for `main`:

- Require pull request before merging.
- Require at least one approving review.
- Require CODEOWNERS review.
- Require status checks:
  - `API tests`
  - `Web typecheck and build`
  - `Docker Compose config`
- Require branches to be up to date before merging.
- Restrict force pushes and deletions.

The canonical repository is public and supports branch protection and repository
rulesets on GitHub Free. Keep the `main` protection rules enabled and do not use
PR-only process discipline as a substitute for enforced checks.

Create GitHub Environments:

- `staging`: deploy allowed for maintainers.
- `production`: deploy requires manual approval.

The canonical repository is public and supports environments and deployment
protection rules on GitHub Free. Keep production secrets in the `production`
environment and require an authorized reviewer before deployment.

## Required Secrets

- `OCI_HOST`
- `OCI_USER`
- `OCI_SSH_PRIVATE_KEY`
- `AMX_PRODUCTION_PATH`
- `AMX_STAGING_ROOT`
- `PRODUCTION_BASE_URL`
- `STAGING_BASE_URL`

## Required Labels

Use these labels for routing and review:

- `agent-task`
- `agent-codex`
- `agent-antigravity`
- `agent-claude`
- `gitnexus-required`
- `needs-acceptance`
- `infra`

## PR Governance Workflow

The `Collaboration governance` workflow enforces the minimum PR evidence contract:

- Purpose;
- Scope;
- Evidence;
- Risk And Rollback;
- Agent Attribution;
- GitNexus Impact Record.

This workflow is not a replacement for protected branches. It is an automated lint gate that prevents empty or evidence-free PR descriptions from entering review.

Use `docs/runbooks/development-verification-standard.md` to decide which checks must be run locally before PR. GitHub Actions are the standard broad PR gate, so agents should not duplicate every CI check locally unless the branch is high-risk or a CI failure is being debugged.

## Git Transport Fallback

Default branch publication is still normal Git:

```powershell
git push -u origin <branch>
```

If Git HTTPS transport is blocked or `git-remote-https.exe` crashes, but `gh api` is authenticated and reachable, publish the already committed local branch through the GitHub Git Data API:

```powershell
powershell -ExecutionPolicy Bypass -File infra\scripts\publish-branch-via-github-api.ps1 `
  -RepoPath C:\amx\AMX-main `
  -OwnerRepo BizYan/AMX `
  -Branch <branch> `
  -BaseRef main `
  -CommitMessage "<commit subject>"
```

Use `-DryRun` first when validating the target repo, branch, base ref, and changed-file list:

```powershell
powershell -ExecutionPolicy Bypass -File infra\scripts\publish-branch-via-github-api.ps1 `
  -RepoPath C:\amx\AMX-main `
  -OwnerRepo BizYan/AMX `
  -Branch <branch> `
  -BaseRef main `
  -DryRun
```

This fallback is only for publishing committed branch contents when Git transport is unavailable. It is not a replacement for PR governance, CI, review, or release validation. PR evidence must state that the branch was published through the GitHub Git Data API and include the remote commit SHA printed by the script.

## PR Size And Evidence

PRs should be reviewable functional units, not process-heavy fragments. Prefer one backend capability, one page interaction closure, one API client plus synchronized callers, one focused bug fix with a regression test, or one coherent documentation/governance update.

Avoid one-field, one-import, one-copy, one-path, or one-test-assertion PRs unless they are urgent hotfixes. Also avoid bundling unrelated capabilities only to reduce PR count.

Every PR must state:

- risk level: Low, Medium, High, or Release;
- local focused verification that was run;
- checks intentionally not run locally and why;
- GitNexus evidence or fallback note;
- rollback plan.

## Merge And Release Policy

Merging a PR is not automatically a production release. Multiple accepted PRs may be grouped into a release slice and validated together when that reduces repeated deployment overhead.

Deploy immediately only for approved hotfixes or when the human owner explicitly asks for same-slice release. Production deployment still goes through GitHub Actions and release validation.

## Agent Rules

- Agents may create branches and PRs.
- Agents may deploy staging from their PR branch.
- Agents may not merge to `main`.
- Agents may not deploy production.
- Every PR must include command output, risk, rollback, and agent attribution.
