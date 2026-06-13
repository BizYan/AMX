# GitNexus Change Record Wrapper

Use `infra\scripts\invoke-gitnexus-change-record.ps1` for PR impact evidence instead of raw `gitnexus detect-changes`.

The wrapper exists because local development often has multiple indexed worktrees with the same repository name, and because `gitnexus detect-changes` maps Git hunks to indexed symbols rather than acting as a complete file-change detector.

The wrapper records four separate facts:

- exact repository path passed to GitNexus;
- Git changed files from the selected diff scope;
- Git untracked files from `git ls-files --others --exclude-standard`;
- GitNexus symbol or flow mapping output.

If Git reports changed files but GitNexus returns `No changes detected`, zero indexed symbols, or fewer changed files than Git reports, the wrapper prints:

```text
Fallback required: True
```

In that case, do not describe the PR as having no GitNexus impact. Describe it as low-value or partial GitNexus symbol evidence and use the changed-file list plus focused verification as the impact record.

Recommended command:

```powershell
powershell -ExecutionPolicy Bypass -File infra\scripts\invoke-gitnexus-change-record.ps1 `
  -RepoPath C:\amx\AMX-main `
  -Scope compare `
  -BaseRef main
```
