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
5. Run smoke tests against staging or the release-critical local route set.
6. Create release tag when cutting a versioned release:

```bash
git checkout main
git pull --ff-only
git tag -a v0.3.0 -m "AMX v0.3.0"
git push origin v0.3.0
```

7. Use GitHub production deployment workflow with the release tag or approved release ref.
8. Verify production health, OCI commit/status, and GitNexus service health/index refresh.
9. Record health check output and any smoke evidence in release notes.

## Release Validation Scope

Always verify:

- GitHub Actions deploy workflow result;
- `/health` output;
- authenticated production smoke for login, current user, projects, documents, readiness, and commissioning;
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
