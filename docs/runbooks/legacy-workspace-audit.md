# Legacy Workspace Audit Runbook

Use this runbook before archiving or deleting old local ConsultantAIP directories.

## Scope

The canonical workspace is:

```text
C:\amx\ConsultantAIP-main
```

Legacy directories currently requiring review are:

```text
C:\ConsultantAIP
C:\ConsultantAIP_antigravity
C:\ConsultantAIP_push_tmp
```

Do not delete `C:\amx`.

## Audit

Run the non-destructive audit from the canonical repository:

```powershell
cd C:\amx\ConsultantAIP-main
powershell -ExecutionPolicy Bypass -File infra\scripts\audit-legacy-workspaces.ps1
```

The script writes a Markdown report and a JSON report to:

```text
C:\amx\reports
```

The report groups files into:

- `Exact matches`: same relative path and same SHA256 as the canonical workspace.
- `Same path different content`: same relative path but different SHA256; review before overwriting or deleting.
- `Content present elsewhere`: byte-identical content exists in the canonical workspace under another path.
- `Unique candidates`: no same-path match and no byte-identical content in the canonical workspace.

## Decision Rules

1. Review every `Unique candidate` before archiving or deletion.
2. Review every `Same path different content` entry that looks like a document, patch, migration, configuration, or unmerged source change.
3. Migrate useful documents, patches, or source changes into `C:\amx\ConsultantAIP-main` through a normal branch and PR.
4. Archive old directories to `C:\amx\archive` only after migration is complete and reviewed.
5. Delete old directories only after the archive is verified or the human owner explicitly confirms deletion.

## Evidence

For any cleanup PR or operations note, record:

- report path and timestamp;
- legacy directories checked;
- count of unique candidates;
- count of same-path different files reviewed;
- final action: no action, migrate, archive, or delete.

The audit script itself is evidence gathering only. It is not approval to remove files.
