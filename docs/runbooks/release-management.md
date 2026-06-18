# Release Management Runbook

## Versioning

Use semantic versioning:

- `v0.1.0`: first usable baseline.
- `v0.2.0`: core product hardening baseline.
- `v0.3.0`: engineering control plane and multi-agent infrastructure.
- Patch versions such as `v0.3.1`: production fixes only.

## Release Checklist

Merging a PR is not automatically a production release. Group stable PRs into a release slice when possible, then validate that slice once. Deploy immediately only for approved hotfixes or when the human owner explicitly asks for same-slice release.

1. Merge all accepted feature branches into the release branch or confirm `main` is the intended release ref.
2. Run `pwsh infra/scripts/test-delivery-readiness.ps1` and resolve every reported blocker.
3. Run CI on the release ref, including deterministic Playwright E2E.
4. Deploy staging when the slice changes release-critical flows or infrastructure.
5. Run smoke tests against staging or the release-critical local route set. Real API smoke evidence is mandatory for a production release and must come from `bash infra/deploy/authenticated-smoke.sh` with configured credentials; deterministic mock E2E is not a substitute.
6. Create release tag when cutting a versioned release. Pushing the tag triggers
   the Release workflow, which validates the release and publishes the GitHub
   Release entry after all quality gates pass:

```bash
git checkout main
git pull --ff-only
git tag -a v0.3.0 -m "AMX v0.3.0"
git push origin v0.3.0
```

7. Use GitHub production deployment workflow with the release tag or approved release ref.
8. Verify production health, OCI commit/status, and GitNexus service health/index refresh.
9. Confirm both the GitHub Release entry and GitHub production Deployment show
   success. A deployment without a GitHub Release is not a completed versioned
   release.
10. Record health check output and any smoke evidence in release notes.

For the proposed v1.0 release, use these evidence artifacts before tagging:

- `docs/releases/v1.0.0.md`
- `docs/programs/v1.0-acceptance-report.md`
- `docs/runbooks/v1.0-rollback.md`

Do not create the `v1.0.0` tag until every release criterion has either passing evidence or an owner-accepted documented gap. Real authenticated API smoke remains mandatory for production promotion and must not be replaced by deterministic mock E2E.

For `v1.0.0`, candidate verification must run through the manual-only
`Candidate verification` workflow before tagging. The workflow must verify the
exact release-candidate SHA in an isolated Compose project, use candidate-only
secrets, run historical migration compatibility baseline verification, run
authenticated smoke with `BOOTSTRAP_ADMIN_EMAIL` and
`BOOTSTRAP_ADMIN_PASSWORD`, upload evidence artifacts, and tear down the
candidate stack. Do not dispatch the production deployment workflow or create a
tag as part of candidate verification.

The candidate migration gate is not a clean empty-database full-history migration proof.
It uses the documented repository compatibility baseline:
stamp `0021_invitation_delivery`, provide the minimal legacy
`projects`/`documents` fixture columns required by current ORM smoke paths,
then run upgrade, downgrade to `0021_invitation_delivery`, and upgrade again.
Clean full-history migration coverage remains the responsibility of the
repository Alembic/CI migration checks.

Candidate runtime startup scope is intentionally limited to `postgres`,
`redis`, and `api`. `worker` and `web` must remain config-isolated in the
rendered Compose config, but this workflow does not runtime-verify them.

## Release Validation Scope

Always verify:

- GitHub Actions deploy workflow result;
- `/health` output;
- authenticated production smoke for login, current user, projects, documents, readiness, and commissioning;
- real API smoke evidence for provider readiness and quota or ops readiness;
- OCI deployed git commit, requested-ref match, tracked working tree status, and required running services;
- GitNexus service health and index refresh status.

Run smoke E2E or route smoke when the release changes:

- login, navigation, or global layout;
- document generation, upload, export, or review flows;
- destructive operations;
- auth, permission, worker, migration, or deployment behavior.

## Rollback Decision

Rollback immediately if:

- `/health` fails after deployment retries;
- login fails for the bootstrap admin;
- web returns a client-side exception on dashboard, projects, documents, or settings;
- worker exits repeatedly;
- migration fails or leaves API restarting.
