# Security Policy

## Reporting A Vulnerability

Do not open a public issue for suspected vulnerabilities, exposed credentials,
or production security incidents. Report them privately to the repository owner
through GitHub's private vulnerability reporting channel.

Include the affected component, reproduction steps, impact, and any suggested
mitigation. Do not include real credentials, customer data, or production data.

## Secrets And Configuration

- Never commit `.env` files, private keys, tokens, passwords, or production data.
- Keep local secrets in ignored environment files.
- Keep deployment secrets in GitHub Environments or the production host.
- Treat values in `*.example` files as non-production placeholders only.
- Revoke and rotate any credential that may have been exposed.

## Supported Version

Security fixes are applied to the current `main` branch.
