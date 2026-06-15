# Evidence-Driven Continuous Improvement

This runbook turns recurring failures, user corrections, and delivery evidence into validated improvements without adding a full retrospective to every task.

## Authoritative Artifacts

- Registry: `docs/continuous-improvement/registry.json`
- Validator: `infra/scripts/check_continuous_improvement_registry.py`
- Project rules: `AGENTS.md`
- Installed audit Skill: `evidence-driven-process-improvement`

## When To Run The Loop

Run a focused improvement review when at least one condition is true:

- the same failure or user correction occurs twice;
- a P0/P1 release, deployment, production, security, or data-integrity failure occurs;
- a Skill has been used at least three times and its trigger behavior or value is uncertain;
- a major release closes;
- the human owner explicitly requests process improvement or historical analysis.

Do not run a full review after routine successful work.

## Lifecycle

```text
observed -> candidate -> validated -> adopted
                      \-> rejected
```

| Status | Meaning | Minimum evidence |
| --- | --- | --- |
| `observed` | A credible issue has been recorded. | Concrete repository path, PR, run, or user correction summary. |
| `candidate` | A specific rule, Skill, validator, script, or test change is proposed. | Evidence plus proposed change and destination. |
| `validated` | A real or representative task showed the candidate improved the result. | Passing validation record and comparison summary. |
| `adopted` | The validated change is installed in an authoritative location. | Passing validation and adopted destination. |
| `rejected` | The candidate was not useful or added excessive friction. | Rejection reason and evidence. |

Do not move directly from `observed` or `candidate` to `adopted`.

## Focused Review Procedure

1. Select only recurring, severe, or materially expensive issues.
2. Add or update registry evidence. Do not create duplicate entries for the same failure mode.
3. Decide the narrowest destination:
   - `AGENTS.md` for durable project-wide behavior;
   - a Skill for a reusable, explicitly triggered workflow;
   - a validator or test for deterministic correctness;
   - a script for repeated fragile commands;
   - `rejected` or no action when ceremony would exceed value.
4. Create a candidate change without overwriting authoritative behavior.
5. Validate it against one real historical task or an explicitly labelled fixture.
6. Compare the before and after result, including added friction.
7. Adopt only when evidence shows the candidate reduces recurrence, risk, or total effort.
8. Record the next review date. Close low-value candidates rather than keeping an indefinite backlog.

## Registry Commands

Validate the registry:

```powershell
python infra/scripts/check_continuous_improvement_registry.py
```

Generate a concise human review report:

```powershell
python infra/scripts/check_continuous_improvement_registry.py `
  --report reports/continuous-improvement-review.md
```

Run focused validator tests:

```powershell
python -m unittest infra.scripts.test_check_continuous_improvement_registry -v
```

## Evidence Rules

- Prefer repository paths, PR URLs, workflow run URLs, and production evidence.
- Never record secrets, tokens, private keys, `.env` content, or personal files.
- Distinguish draft, mock, dry-run, local validation, merge, release, deployment, and production verification.
- Mark unavailable evidence explicitly; never invent it.
- File count and report count are not quality measures.

## Review Cadence

- Review P0 entries after every related incident or release.
- Review P1 entries monthly or after the next three relevant executions.
- Review P2 entries quarterly.
- Reject or archive candidates that show no measurable value.

The human owner retains authority over permanent project-rule changes, installed Skills, releases, and production actions.

