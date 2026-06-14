# Project Invitation Delivery Governance Design

## Outcome

Close the gap between creating an invitation and proving it reached the intended recipient. Project owners can record successful or failed external delivery, inspect attempt counts and failure reasons, renew expired or failed invitations, and retain audit evidence without persisting raw invitation tokens.

## Design

- Persist delivery status, channel, attempt count, failure reason, latest attempt, and latest successful delivery on each invitation.
- Keep token delivery external because the platform has no configured transactional-email provider.
- Record owner-confirmed delivery evidence through a dedicated endpoint.
- Reset delivery state to pending whenever an invitation is renewed and its token rotates.
- Reject delivery updates after acceptance or revocation.
- Show delivery coverage and actions in the project-members workbench.

## Security

- Raw invitation tokens remain one-time API responses and never enter delivery metadata or audit logs.
- Only the project owner can update delivery evidence.
- Renewal invalidates the old token before a new delivery is recorded.
