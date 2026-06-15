# Evidence-Driven Continuous Improvement Design

## Goal

Create a lightweight mechanism that converts repeated failures, user corrections, and verified delivery lessons into reviewable improvements to project rules, Skills, validators, or scripts.

## Principles

- Use repository evidence, not broad scans of the user's computer.
- Record a problem only when it is recurring, severe, or materially expensive.
- Generate and validate candidates before adopting permanent rules.
- Do not confuse mock, local verification, merge, release, deployment, or production verification.
- Keep the mechanism small enough that it reduces work rather than becoming another reporting burden.

## Components

1. `docs/runbooks/continuous-improvement.md` defines triggers, lifecycle, review cadence, and responsibilities.
2. `docs/continuous-improvement/registry.json` stores structured improvement records and their evidence.
3. `infra/scripts/check_continuous_improvement_registry.py` validates the registry and can generate a concise review report.
4. Collaboration governance CI validates the registry whenever repository changes are proposed.
5. `AGENTS.md` requires agents to record repeated failures and forbids direct adoption without evidence.
6. A local Codex Skill guides future evidence-driven improvement audits without triggering during routine development.

## Lifecycle

```text
observed -> candidate -> validated -> adopted
                      \-> rejected
```

- `observed`: credible issue with evidence, but no proposed permanent change.
- `candidate`: a concrete rule, Skill, validator, script, or test change is proposed.
- `validated`: the candidate improved a real or representative task.
- `adopted`: the improvement is installed in the authoritative location.
- `rejected`: evidence showed insufficient value, excessive friction, or harmful side effects.

## Trigger Policy

Run the improvement loop when any condition is met:

- the same failure or user correction occurs twice;
- a P0/P1 release or production failure occurs;
- a Skill has been used at least three times and its value or trigger behavior is uncertain;
- a major release closes;
- the user explicitly requests a process or capability review.

Routine successful tasks do not trigger a full audit.

## Validation

The registry validator enforces required fields, valid lifecycle states, evidence, destinations, validation results, and unique identifiers. CI checks structure only. Human review decides whether a candidate is useful and whether it should be adopted.

## Safety

- No automatic edits to installed Skills or authoritative project rules.
- No automatic production actions.
- No secret, browser-profile, home-directory, or unrelated-project scans.
- No large report bundle; manual audits produce one concise Markdown report.

