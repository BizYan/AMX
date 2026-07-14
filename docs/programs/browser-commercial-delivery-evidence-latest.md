# Browser Commercial Delivery Evidence Latest

Date: 2026-07-15

Status: successful isolated staging evidence. This is real browser evidence for
the verified staging SHA. It is not a production-browser readiness claim and
does not authorize a release by itself.

## Verified Target

- Target: disposable isolated staging slot.
- SHA: `66a09e0dd566df2838ba62766323180d49cc3867`.
- Workflow: [Deploy staging run 29375316574](https://github.com/BizYan/AMX/actions/runs/29375316574).
- Conclusion: `success`.
- Staging slot: `real-browser-66a09e0d`.
- Compose project: `amx_staging_real_browser_66a09e0d_66a09e0dd566`.
- Database: `amx_staging_real_browser_66a09e0d_66a09e0dd566`.
- Network: `amx_staging_real_browser_66a09e0d_66a09e0dd566_network`.
- Isolation, historical migration compatibility baseline, health, and teardown:
  passed.

The application returned `{"status":"healthy","version":"1.0.0"}`. The
workflow checkout and staging runtime summary bind this evidence to the full
SHA above; the application version field is not release provenance.

## Real Browser Journey

The gated Playwright journey ran with real browser login and real backend calls.
It did not use `setupApiMocks`, `page.route`, fake JWTs, or fixture-only data.
All created business records used synthetic material and the staging slot was
torn down after evidence collection.

| Evidence | Sanitized value |
| --- | --- |
| Source marker | `AMX-REAL-BROWSER-1784070819072` |
| Project | `648c7163-ed0d-4882-b43a-760a4a2a511c` |
| Source file | `4fbd241d-0057-4316-aec1-14567615b76c` |
| Ingestion job | `27fe82d4-3a45-46c6-a47f-474f7e1e14ae` |
| Knowledge entry | `1310a740-d66a-4467-8504-abfd3823d5f0` |
| Document | `1bb1d8d6-d616-430c-800b-878215d13acd` |
| Version / baseline | `85099113-c90e-4199-b8ab-30cc81c995a2` / `1c04f201-7d46-42cd-af86-2395f0086755` |
| Export job / artifact | `06f85288-e58b-4f07-9df6-0022d7f53c71` / `1ed7e291-3702-43c1-8d4a-dfda192171ac` |
| Portal link | `8caa36b9-68ee-4a44-94a3-acc8803b30f3` |
| Acceptance / closeout | `decision=accepted;closed=true` |
| Sanitized audit evidence | `04546704-afd2-4531-a0bb-21d49e17bb8f` |

The successful path covers login, synthetic project creation, source upload,
ingestion, knowledge/provenance, provider-backed document selection or
generation through the normal UI path, review resolution, approval/publication,
package export, token-scoped portal download, acceptance, delivery closeout, and
sanitized audit visibility.

## Blocked-Path Evidence

The same run verified these enforced boundaries:

- unresolved comment blocks approval;
- package-not-ready blocks customer portal delivery;
- revoked customer token is denied;
- customer token cannot access internal API routes.

## Evidence Artifacts

The workflow artifact `staging-commercial-journey-evidence` contains sanitized
runtime summary, health, isolation, historical-migration-baseline, teardown,
Playwright screenshots, and `commercial-delivery-evidence.json`.

Screenshots:

- `01-source-knowledge.png`
- `02-customer-portal.png`
- `03-sanitized-audit.png`

No credentials, tokens, raw customer content, or environment files are part of
the recorded evidence.

## Cleanup And Limitations

- Application cleanup: the synthetic project was archived.
- Infrastructure cleanup: `teardown=passed` for the disposable staging slot.
- This does not prove a production browser journey, production deployment,
  production provenance, or customer-data handling.
- Current-main promotion still requires exact-SHA candidate verification, normal
  release gates, and a production deployment workflow before it can supersede
  the verified production release.
