# Security And Secrets Runbook

## Secrets Policy

- Do not commit `.env`, private keys, API keys, tokens, or Cloudflare origin private keys.
- GitHub Actions secrets are the only approved path for CI/CD deployment credentials.
- Production `.env` stays on OCI under the deployment directory.
- Production `.env` must be owner-only (`chmod 600`).
- Agent task prompts must not include raw tokens or private keys.
- Provider registration and provider version config must not persist raw
  credentials such as `api_key`, `token`, `access_token`, `secret`, or
  `service_key`. Store only non-secret metadata and `credential_ref` /
  `secret_ref` values.
- Candidate or staging provider validation may resolve `credential_ref` values
  from runtime environment variables such as `env:AMX_CANDIDATE_LLM_API_KEY`.
  The resolved secret must never be written back to provider config, API
  responses, logs, audit records, exports, or evidence artifacts.
- Real document-generation provider commissioning requires an owner-approved
  spend cap before the first live call. The default candidate cap is the first
  of USD 5 total spend, 50 generation calls, or 100k tokens.

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
- GitHub Environment or isolated candidate runtime secrets for temporary
  provider validation. Do not use Provider `config_json` or provider version
  config as a secret store.

## Dependency Security

- CI rejects known high or critical Web production dependency vulnerabilities.
- CI audits the complete locked API environment with `pip-audit`.
- Dependabot groups weekly Web and API patch/minor maintenance updates. Major
  upgrades require an explicit engineering slice because they may change
  framework or runtime contracts.
- Collaboration governance compares dependency manifests against the PR base
  and rejects Dependabot changes that cross or remove a protected major-version
  boundary. Python compatibility caps must include an explicit lower bound so
  automation can distinguish maintenance updates from major migrations.
- Dependabot PRs may bypass the human/agent evidence-body format only when
  their diff is limited to approved dependency manifests and lockfiles; all
  normal CI checks remain required.
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
