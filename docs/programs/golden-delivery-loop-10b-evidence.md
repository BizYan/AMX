# Golden Delivery Loop 10B Evidence

## Scope

Golden Delivery Loop 10B covers the real evidence path from source-backed
knowledge to AI-generated document, review, approval, baseline, and export
package.

In scope:

- source-backed knowledge marker in generation context;
- real document generation contract with provider/model/usage evidence;
- provider run persistence without credential exposure;
- review comment creation and resolution;
- document version and baseline creation;
- lifecycle transition through review, approved, and published;
- export readiness and project package generation;
- package content proof that the generated document, not fixture or placeholder
  content, is exported.

Out of scope:

- provider configuration;
- credential inspection, printing, or rotation;
- production deployment;
- release tagging;
- customer portal acceptance.

## Evidence Boundary

Focused backend tests use synthetic source material and a controlled provider
adapter to prove contracts, state transitions, gates, and artifact contents.
They are regression evidence, not proof that a live provider was called.

Candidate or staging verification must run only in an isolated environment where
the Owner has configured the candidate-only provider secret reference and spend
cap. The verification must not print or persist raw credentials.

Required candidate evidence:

- exact SHA and runtime identity;
- synthetic project/source/document IDs;
- provider name and model identity;
- provider run ID with token usage;
- source grounding knowledge entry and source file IDs;
- generated document status `generated`;
- review comment resolved;
- version and baseline IDs;
- final lifecycle status `published`;
- export job and artifact IDs;
- exported artifact contains the synthetic marker and generated document text;
- logs, API payloads, DB fixtures, exports, and PR text contain no provider
  credential.

## Blocked Paths

10B must block:

- unavailable or misconfigured provider output from entering review, approval,
  publication, or export;
- `placeholder`, `partial`, and `failed` AI generation states from project
  package export;
- unresolved comments from publishing when the project lifecycle policy requires
  resolved comments;
- document-level delivery readiness failure from export.
