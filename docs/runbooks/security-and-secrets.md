# Security And Secrets Runbook

## Secrets Policy

- Do not commit `.env`, private keys, API keys, tokens, or Cloudflare origin private keys.
- GitHub Actions secrets are the only approved path for CI/CD deployment credentials.
- Production `.env` stays on OCI under the deployment directory.
- Production `.env` must be owner-only (`chmod 600`).
- Agent task prompts must not include raw tokens or private keys.

## Runtime Network Exposure

- PostgreSQL, Redis, API, and Web host ports bind to `127.0.0.1` by default.
- Production deployments reject non-loopback `*_BIND_ADDRESS` values.
- Public traffic enters through Nginx on ports 80/443 only.
- Use SSH tunneling or `docker compose exec` for database and Redis operations;
  do not expose their host ports publicly.

## Required Secret Stores

- GitHub repository secrets for deploy automation.
- OCI filesystem for production `.env`.
- Cloudflare dashboard for DNS and SSL mode.

## Dependency Security

- CI rejects known high or critical Web production dependency vulnerabilities.
- CI audits the complete locked API environment with `pip-audit`.
- Dependabot groups weekly Web and API dependency maintenance updates.
- Security dependency PRs must preserve lockfiles and pass the normal API, Web,
  Compose, governance, and deterministic E2E gates before merge.

## SSH Key Handling

Store deploy private key only in:

- GitHub secret `OCI_SSH_PRIVATE_KEY`;
- local operator machine key store;
- never in the repository.

## Incident Response

If a credential is exposed:

1. Revoke it at the issuer.
2. Rotate dependent services.
3. Search repository history and local docs for copies.
4. Open a security issue recording scope and remediation.
