# Account Security And Identity Lifecycle Design

## Outcome

Provide a production account-security loop in which users can inspect security evidence, change passwords, revoke every issued session, and deactivate their own account. Administrative deactivation and password reset must invalidate existing sessions as well.

## Design

- Add a monotonic `users.security_version` claim to every access token.
- Reject tokens whose claim no longer matches the current user record.
- Increment the version after password change, session revocation, self-deactivation, administrative deactivation, or administrative password reset.
- Persist `password_changed_at` and `last_login_at`.
- Record password, session, and account lifecycle actions in the existing audit log.
- Expose a self-service account-security panel in Team Settings.

## Security Properties

- Existing JWTs become invalid without maintaining a per-session database.
- Password changes require current-password verification and reject reuse.
- Self-deactivation immediately blocks login.
- Tenant administrators cannot deactivate or reset a user while leaving old tokens valid.
