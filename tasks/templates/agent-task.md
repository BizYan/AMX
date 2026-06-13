# Task: <title>

## 1. Owner And Role

- Human sponsor:
- Agent owner:
- Reviewer:
- Target branch:
- Related issue / PR:

## 2. Business Goal

Describe the outcome in user-facing terms.

## 3. Scope

### In Scope

-

### Out Of Scope

-

## 4. Current Facts

- Relevant routes:
- Relevant API endpoints:
- Relevant backend modules:
- Relevant database tables / migrations:
- Relevant tests:

## 5. GitNexus Initial Impact Analysis

If GitNexus is unavailable, state that explicitly and list the fallback search commands used.

### Freshness

```text
gitnexus status
```

- Indexed commit:
- Current commit:
- Status:

### Query Targets

-

### Commands / MCP Tools Used

```text
gitnexus query "<task>" --goal "<goal>" --limit 10
gitnexus impact "<symbol>" --direction upstream --depth 3 --include-tests
```

### Affected Modules

-

### Existing Reusable Implementation

-

### Page -> API -> Service -> Data / Worker Chain

-

### Required Regression Paths

-

## 6. Implementation Requirements

-

## 7. Verification Requirements

Required commands:

```text
pnpm --dir apps/web typecheck
pnpm --dir apps/web build
uv run --directory apps/api pytest
```

Additional task-specific verification:

-

## 8. Acceptance Criteria

- [ ] User-facing flow works.
- [ ] No white screen, client-side exception, or visible 404.
- [ ] Buttons and links provide action, navigation, or clear feedback.
- [ ] Chinese production copy is complete for affected pages.
- [ ] Tests pass and evidence is recorded.
- [ ] GitNexus impact analysis or fallback analysis is recorded.

## 9. Risk And Rollback

- Risk:
- Rollback:

## 10. Delivery Report

Fill this section before PR:

- Commands run:
- Results:
- GitNexus post-change command:
- GitNexus post-change result:
- Files changed:
- Known limitations:
- Screenshots / traces:
