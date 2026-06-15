# Evidence-Driven Continuous Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight, evidence-driven process that turns recurring failures and user corrections into validated project improvements.

**Architecture:** Store improvement records in a versioned JSON registry, validate them with a deterministic Python script, document the lifecycle in a runbook, and enforce registry validity in collaboration governance CI. Add a narrowly triggered local Codex Skill for future audits.

**Tech Stack:** Markdown, JSON, Python standard library, GitHub Actions, Codex Skills

---

### Task 1: Define the mechanism and initial evidence

**Files:**
- Create: `docs/runbooks/continuous-improvement.md`
- Create: `docs/continuous-improvement/registry.json`
- Modify: `AGENTS.md`

- [ ] Document triggers, lifecycle, evidence requirements, review cadence, and adoption rules.
- [ ] Seed the registry with recurring issues already supported by repository evidence.
- [ ] Add concise agent rules that point to the runbook and registry.

### Task 2: Add deterministic registry validation

**Files:**
- Create: `infra/scripts/check_continuous_improvement_registry.py`
- Create: `infra/scripts/test_check_continuous_improvement_registry.py`

- [ ] Write failing unit tests for valid records, duplicate identifiers, missing evidence, and adoption without passing validation.
- [ ] Implement JSON validation and concise Markdown report generation.
- [ ] Run the focused unit tests and validate the real registry.

### Task 3: Enforce the mechanism in CI

**Files:**
- Modify: `.github/workflows/collaboration-governance.yml`

- [ ] Require the runbook and registry as governance files.
- [ ] Run the registry validator in the repository-contract job.
- [ ] Validate workflow syntax through repository checks.

### Task 4: Install and validate the audit Skill

**Files:**
- Create: `C:\Users\dajid\.codex\skills\evidence-driven-process-improvement\SKILL.md`
- Create: `C:\Users\dajid\.codex\skills\evidence-driven-process-improvement\agents\openai.yaml`

- [ ] Define narrow trigger language and the candidate-first audit workflow.
- [ ] Validate the Skill structure.
- [ ] Run a semi-real audit against the seeded registry and produce one concise report.

### Task 5: Verify and prepare delivery

- [ ] Run focused Python tests.
- [ ] Validate the real registry and generated report.
- [ ] Run `git diff --check`.
- [ ] Run the GitNexus change-record wrapper.
- [ ] Review the final diff and prepare a focused commit and PR.

