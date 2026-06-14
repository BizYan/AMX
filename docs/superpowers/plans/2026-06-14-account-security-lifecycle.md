# Account Security And Identity Lifecycle Implementation Plan

1. Add user security-version and lifecycle timestamps with an Alembic migration.
2. Include security-version in JWT issuance and enforce it during authentication.
3. Add password-change, revoke-all-sessions, self-deactivation, and security-evidence APIs.
4. Ensure administrative deactivation and password reset revoke sessions.
5. Add the account-security settings panel and deterministic E2E coverage.
6. Run focused API tests, migration checks, typecheck, build, and E2E before PR creation.
