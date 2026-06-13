<#
.SYNOPSIS
Creates a GitNexus PR change record with a git-diff fallback.

.DESCRIPTION
GitNexus detect-changes maps git diffs to symbols already present in the
indexed graph. In multi-worktree setups the CLI also requires an explicit repo
path. This wrapper standardizes both concerns:

- resolves and passes the current repository path with --repo;
- records the raw git changed-file list, including new files;
- runs one GitNexus detect-changes command;
- writes a Markdown report that can be summarized in PR evidence.
#>

param(
    [string]$RepoPath = "C:\amx\ConsultantAIP-main",
    [ValidateSet("unstaged", "staged", "all", "compare")]
    [string]$Scope = "compare",
    [string]$BaseRef = "main",
    [string]$ReportsDir = "C:\amx\reports",
    [switch]$RefreshIfStale,
    [switch]$NoReport
)

$ErrorActionPreference = "Stop"

function Invoke-Captured {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$WorkingDirectory
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($WorkingDirectory) {
            Push-Location $WorkingDirectory
            try {
                $output = & $Command @Arguments 2>&1
            }
            finally {
                Pop-Location
            }
        }
        else {
            $output = & $Command @Arguments 2>&1
        }
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    [PSCustomObject]@{
        Command = "$Command $($Arguments -join ' ')"
        ExitCode = $exitCode
        Output = (($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()
    }
}

function Add-CommandSection {
    param(
        [System.Collections.Generic.List[string]]$Report,
        [string]$Title,
        $Result
    )

    $Report.Add("## $Title")
    $Report.Add("")
    $Report.Add("Command: " + '``' + $Result.Command + '``')
    $Report.Add("")
    $Report.Add("Exit code: " + '``' + $Result.ExitCode + '``')
    $Report.Add("")
    $Report.Add('```text')
    if ($Result.Output) {
        $Report.Add($Result.Output)
    }
    $Report.Add('```')
    $Report.Add("")
}

if (-not (Test-Path -LiteralPath $RepoPath -PathType Container)) {
    throw "Repository path does not exist: $RepoPath"
}

foreach ($command in @("git", "gitnexus")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command is required for GitNexus change records."
    }
}

$resolvedRepoPath = (Resolve-Path -LiteralPath $RepoPath).Path.TrimEnd([char[]]@('\', '/'))

Push-Location $resolvedRepoPath
try {
    $repoRoot = (git rev-parse --show-toplevel).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
        throw "RepoPath is not a git repository: $resolvedRepoPath"
    }
    $repoRoot = $repoRoot.TrimEnd([char[]]@('\', '/'))

    $status = Invoke-Captured gitnexus @("status") $repoRoot
    $refresh = $null
    if ($RefreshIfStale -and $status.Output -notmatch "up-to-date") {
        $refresh = Invoke-Captured gitnexus @("analyze", "--index-only") $repoRoot
        $status = Invoke-Captured gitnexus @("status") $repoRoot
    }

    switch ($Scope) {
        "staged" {
            $gitDiffArgs = @("diff", "--staged", "--name-status")
            $detectArgs = @("detect-changes", "--scope", "staged", "--repo", $repoRoot)
        }
        "all" {
            $gitDiffArgs = @("diff", "HEAD", "--name-status")
            $detectArgs = @("detect-changes", "--scope", "all", "--repo", $repoRoot)
        }
        "unstaged" {
            $gitDiffArgs = @("diff", "--name-status")
            $detectArgs = @("detect-changes", "--scope", "unstaged", "--repo", $repoRoot)
        }
        "compare" {
            $gitDiffArgs = @("diff", $BaseRef, "--name-status")
            $detectArgs = @("detect-changes", "--scope", "compare", "--base-ref", $BaseRef, "--repo", $repoRoot)
        }
    }

    $branch = Invoke-Captured git @("branch", "--show-current") $repoRoot
    $commit = Invoke-Captured git @("log", "-1", "--oneline") $repoRoot
    $gitStatus = Invoke-Captured git @("status", "-sb") $repoRoot
    $gitChangedFiles = Invoke-Captured git $gitDiffArgs $repoRoot
    $gitUntrackedFiles = Invoke-Captured git @("ls-files", "--others", "--exclude-standard") $repoRoot
    $gitnexusChanges = Invoke-Captured gitnexus $detectArgs $repoRoot

    $trackedChangeLines = @()
    if ($gitChangedFiles.Output) {
        $trackedChangeLines = @(
            $gitChangedFiles.Output -split '\r?\n' |
                Where-Object { $_.Trim() -match '^[ACDMRTUXB][0-9]*\s+' }
        )
    }
    $untrackedFileLines = @()
    if ($gitUntrackedFiles.Output) {
        $untrackedFileLines = @(
            $gitUntrackedFiles.Output -split '\r?\n' |
                Where-Object { $_.Trim() -and $_.Trim() -notmatch '^(git|node)\.exe\s+:' } |
                ForEach-Object { "??`t$($_.Trim())" }
        )
    }
    $changedFileLines = @($trackedChangeLines + $untrackedFileLines)

    $gitHasChanges = $changedFileLines.Count -gt 0
    $gitnexusMappedNoSymbols =
        $gitnexusChanges.Output -match "No changes detected" -or
        $gitnexusChanges.Output -match "Changed symbols:\s*$"

    $gitnexusChangedFileCount = $null
    if ($gitnexusChanges.Output -match "Changes:\s+(\d+)\s+files") {
        $gitnexusChangedFileCount = [int]$Matches[1]
    }
    $gitnexusPartialFileCoverage =
        $null -ne $gitnexusChangedFileCount -and
        $gitnexusChangedFileCount -lt $changedFileLines.Count

    $gitEvidenceStatus = if ($gitHasChanges) {
        "changed-files-detected"
    }
    else {
        "no-git-changes-detected"
    }

    $gitnexusSymbolStatus = if ($gitnexusChanges.ExitCode -ne 0) {
        "gitnexus-detect-changes-failed"
    }
    elseif ($gitnexusMappedNoSymbols) {
        "zero-indexed-symbols"
    }
    elseif ($gitnexusPartialFileCoverage) {
        "partial-file-coverage"
    }
    elseif ($gitnexusChanges.Output) {
        "symbol-output-returned"
    }
    else {
        "empty-output"
    }

    $fallbackRequired =
        ($untrackedFileLines.Count -gt 0) -or
        $gitnexusPartialFileCoverage -or
        ($gitHasChanges -and ($gitnexusChanges.ExitCode -ne 0 -or $gitnexusMappedNoSymbols))

    $interpretation = if ($gitnexusPartialFileCoverage) {
        "Git found $($changedFileLines.Count) changed files, but GitNexus reported $gitnexusChangedFileCount changed files. Use GitNexus symbol output only for the covered files and the raw Git changed-file list as fallback for the rest."
    }
    elseif ($untrackedFileLines.Count -gt 0) {
        "Git found changed files including untracked files. GitNexus detect-changes does not analyze untracked files until they are staged or committed; raw Git evidence is authoritative for file-level impact."
    }
    elseif ($gitHasChanges -and $gitnexusMappedNoSymbols) {
        "Git diff found changed files, but GitNexus mapped zero indexed symbols. Use the changed-file list as fallback impact evidence; this is expected for new docs/scripts or files not present in the current index."
    }
    elseif ($gitHasChanges) {
        "Git diff found changed files and GitNexus returned symbol/process context. Use both records."
    }
    else {
        "Git diff found no changed files for the selected scope."
    }

    $reportPath = $null
    if (-not $NoReport) {
        New-Item -ItemType Directory -Force -Path $ReportsDir | Out-Null
        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $reportPath = Join-Path $ReportsDir "gitnexus-change-record-$timestamp.md"

        $report = New-Object System.Collections.Generic.List[string]
        $report.Add("# GitNexus Change Record")
        $report.Add("")
        $report.Add("- Generated: $(Get-Date -Format o)")
        $report.Add("- Repository: $repoRoot")
        $report.Add("- Scope: $Scope")
        $report.Add("- Base ref: $BaseRef")
        $report.Add("- Changed files: $($changedFileLines.Count)")
        $report.Add("- Git evidence status: $gitEvidenceStatus")
        $report.Add("- GitNexus symbol status: $gitnexusSymbolStatus")
        if ($null -ne $gitnexusChangedFileCount) {
            $report.Add("- GitNexus changed files: $gitnexusChangedFileCount")
        }
        $report.Add("- Fallback required: $fallbackRequired")
        $report.Add("- Interpretation: $interpretation")
        $report.Add("")
        if ($fallbackRequired) {
            $report.Add("> GitNexus did not produce usable symbol impact for files that Git reports as changed. Do not summarize raw `gitnexus detect-changes` as `no changes`; use the Git changed-file list plus focused verification as fallback evidence.")
            $report.Add("")
        }

        Add-CommandSection -Report $report -Title "Git Branch" -Result $branch
        Add-CommandSection -Report $report -Title "Git Commit" -Result $commit
        Add-CommandSection -Report $report -Title "Git Status" -Result $gitStatus
        Add-CommandSection -Report $report -Title "Git Changed Files" -Result $gitChangedFiles
        Add-CommandSection -Report $report -Title "Git Untracked Files" -Result $gitUntrackedFiles
        Add-CommandSection -Report $report -Title "GitNexus Status" -Result $status
        if ($refresh) {
            Add-CommandSection -Report $report -Title "GitNexus Refresh" -Result $refresh
        }
        Add-CommandSection -Report $report -Title "GitNexus Detect Changes" -Result $gitnexusChanges

        Set-Content -Path $reportPath -Value ($report -join [Environment]::NewLine) -Encoding UTF8
    }

    Write-Host "GitNexus change record"
    Write-Host "Repository: $repoRoot"
    Write-Host "Scope: $Scope"
    Write-Host "Base ref: $BaseRef"
    Write-Host "Changed files: $($changedFileLines.Count)"
    Write-Host "Git evidence status: $gitEvidenceStatus"
    Write-Host "GitNexus symbol status: $gitnexusSymbolStatus"
    if ($null -ne $gitnexusChangedFileCount) {
        Write-Host "GitNexus changed files: $gitnexusChangedFileCount"
    }
    Write-Host "Fallback required: $fallbackRequired"
    Write-Host "Interpretation: $interpretation"
    if ($fallbackRequired) {
        Write-Host "Warning: GitNexus did not produce usable symbol impact for files that Git reports as changed. Do not treat raw GitNexus 'no changes' output as no-impact evidence."
    }
    if ($reportPath) {
        Write-Host "Report: $reportPath"
    }

    if ($gitChangedFiles.ExitCode -ne 0) {
        exit $gitChangedFiles.ExitCode
    }
    if ($gitnexusChanges.ExitCode -ne 0) {
        exit $gitnexusChanges.ExitCode
    }
}
finally {
    Pop-Location
}
