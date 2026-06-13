<#
.SYNOPSIS
Creates a non-destructive comparison report for legacy local workspaces.

.DESCRIPTION
This script compares each configured legacy workspace against the current
repository by relative path and SHA256. It writes Markdown and JSON reports
under C:\amx\reports by default, and never deletes, moves, or modifies legacy
files. Use the report to decide which files must be migrated or archived before
removing old local directories.
#>

param(
    [string]$RepoPath = "C:\amx\AMX-main",
    [string[]]$LegacyPaths = @(
        "C:\ConsultantAIP",
        "C:\ConsultantAIP_antigravity",
        "C:\ConsultantAIP_push_tmp"
    ),
    [string]$ReportsDir = "C:\amx\reports",
    [int]$MaxRowsPerSection = 200
)

$ErrorActionPreference = "Stop"

$ExcludedDirectoryNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
@(
    ".git",
    ".gitnexus",
    ".next",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    "node_modules",
    "coverage",
    ".mypy_cache",
    ".ruff_cache"
) | ForEach-Object { [void]$ExcludedDirectoryNames.Add($_) }

function Resolve-DirectoryPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $null
    }
    return (Resolve-Path -LiteralPath $Path).Path.TrimEnd("\", "/")
}

function Get-RelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$RootPath,
        [Parameter(Mandatory = $true)][string]$FullName
    )

    $root = $RootPath.TrimEnd("\", "/")
    $relative = $FullName.Substring($root.Length).TrimStart("\", "/")
    return $relative -replace "\\", "/"
}

function Test-IsExcludedRelativePath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    foreach ($part in ($RelativePath -split "/")) {
        if ($ExcludedDirectoryNames.Contains($part)) {
            return $true
        }
    }
    return $false
}

function Get-SafeHash {
    param([Parameter(Mandatory = $true)][string]$Path)

    try {
        return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    }
    catch {
        return $null
    }
}

function Get-WorkspaceFiles {
    param([Parameter(Mandatory = $true)][string]$RootPath)

    $files = New-Object System.Collections.Generic.List[object]
    Get-ChildItem -LiteralPath $RootPath -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $relativePath = Get-RelativePath -RootPath $RootPath -FullName $_.FullName
        if (Test-IsExcludedRelativePath -RelativePath $relativePath) {
            return
        }

        $files.Add([PSCustomObject]@{
            RelativePath = $relativePath
            FullName = $_.FullName
            SizeBytes = $_.Length
            LastWriteTimeUtc = $_.LastWriteTimeUtc.ToString("o")
            Sha256 = Get-SafeHash -Path $_.FullName
        })
    }
    return $files
}

function New-FileIndexes {
    param([Parameter(Mandatory = $true)]$Files)

    $byRelativePath = @{}
    $byHash = @{}

    foreach ($file in $Files) {
        $byRelativePath[$file.RelativePath] = $file
        if ($file.Sha256) {
            if (-not $byHash.ContainsKey($file.Sha256)) {
                $byHash[$file.Sha256] = New-Object System.Collections.Generic.List[object]
            }
            $byHash[$file.Sha256].Add($file)
        }
    }

    [PSCustomObject]@{
        ByRelativePath = $byRelativePath
        ByHash = $byHash
    }
}

function ConvertTo-MarkdownCell {
    param([AllowNull()][object]$Value)

    if ($null -eq $Value) {
        return ""
    }
    return ([string]$Value).Replace("|", "\|").Replace("`r", " ").Replace("`n", " ")
}

function Add-FileRows {
    param(
        [System.Collections.Generic.List[string]]$Report,
        [string]$Title,
        [array]$Rows,
        [int]$MaxRows
    )

    $Report.Add("### $Title")
    $Report.Add("")
    if (-not $Rows -or $Rows.Count -eq 0) {
        $Report.Add("No entries.")
        $Report.Add("")
        return
    }

    $Report.Add("| Relative path | Size | SHA256 | Matching main paths |")
    $Report.Add("| --- | ---: | --- | --- |")
    foreach ($row in ($Rows | Select-Object -First $MaxRows)) {
        $matchingPaths = if ($row.MatchingMainPaths) { ($row.MatchingMainPaths -join "; ") } else { "" }
        $Report.Add("| $(ConvertTo-MarkdownCell $row.RelativePath) | $($row.SizeBytes) | $(ConvertTo-MarkdownCell $row.Sha256) | $(ConvertTo-MarkdownCell $matchingPaths) |")
    }
    if ($Rows.Count -gt $MaxRows) {
        $Report.Add("")
        $Report.Add("Showing first $MaxRows of $($Rows.Count) entries.")
    }
    $Report.Add("")
}

if (-not (Test-Path -LiteralPath $RepoPath -PathType Container)) {
    throw "Repository path does not exist: $RepoPath"
}

$resolvedRepoPath = Resolve-DirectoryPath -Path $RepoPath
New-Item -ItemType Directory -Force -Path $ReportsDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$reportPath = Join-Path $ReportsDir "legacy-workspace-audit-$timestamp.md"
$jsonPath = Join-Path $ReportsDir "legacy-workspace-audit-$timestamp.json"

$repoFiles = Get-WorkspaceFiles -RootPath $resolvedRepoPath
$repoIndexes = New-FileIndexes -Files $repoFiles

$workspaceResults = New-Object System.Collections.Generic.List[object]

foreach ($legacyPath in $LegacyPaths) {
    $resolvedLegacyPath = Resolve-DirectoryPath -Path $legacyPath
    if (-not $resolvedLegacyPath) {
        $workspaceResults.Add([object]([PSCustomObject]@{
            Path = $legacyPath
            Exists = $false
            TotalFiles = 0
            ExactMatches = @()
            SamePathDifferentContent = @()
            ContentPresentElsewhere = @()
            UniqueCandidates = @()
        }))
        continue
    }

    $legacyFiles = Get-WorkspaceFiles -RootPath $resolvedLegacyPath
    $exactMatches = New-Object System.Collections.Generic.List[object]
    $samePathDifferent = New-Object System.Collections.Generic.List[object]
    $contentElsewhere = New-Object System.Collections.Generic.List[object]
    $uniqueCandidates = New-Object System.Collections.Generic.List[object]

    foreach ($file in $legacyFiles) {
        $samePathMainFile = $repoIndexes.ByRelativePath[$file.RelativePath]
        if ($samePathMainFile -and $samePathMainFile.Sha256 -eq $file.Sha256) {
            $exactMatches.Add($file)
            continue
        }

        if ($samePathMainFile) {
            $samePathDifferent.Add([PSCustomObject]@{
                RelativePath = $file.RelativePath
                FullName = $file.FullName
                SizeBytes = $file.SizeBytes
                LastWriteTimeUtc = $file.LastWriteTimeUtc
                Sha256 = $file.Sha256
                MainSha256 = $samePathMainFile.Sha256
                MatchingMainPaths = @($samePathMainFile.RelativePath)
            })
            continue
        }

        if ($file.Sha256 -and $repoIndexes.ByHash.ContainsKey($file.Sha256)) {
            $matches = @($repoIndexes.ByHash[$file.Sha256] | ForEach-Object { $_.RelativePath })
            $contentElsewhere.Add([PSCustomObject]@{
                RelativePath = $file.RelativePath
                FullName = $file.FullName
                SizeBytes = $file.SizeBytes
                LastWriteTimeUtc = $file.LastWriteTimeUtc
                Sha256 = $file.Sha256
                MatchingMainPaths = $matches
            })
            continue
        }

        $uniqueCandidates.Add($file)
    }

    $workspaceResults.Add([object]([PSCustomObject]@{
        Path = $resolvedLegacyPath
        Exists = $true
        TotalFiles = $legacyFiles.Count
        ExactMatches = @($exactMatches.ToArray())
        SamePathDifferentContent = @($samePathDifferent.ToArray())
        ContentPresentElsewhere = @($contentElsewhere.ToArray())
        UniqueCandidates = @($uniqueCandidates.ToArray())
    }))
}

$report = New-Object System.Collections.Generic.List[string]
$report.Add("# Legacy Workspace Audit")
$report.Add("")
$report.Add("- Generated: $(Get-Date -Format o)")
$report.Add("- Repository: $resolvedRepoPath")
$report.Add("- Repository files indexed: $($repoFiles.Count)")
$report.Add("- Report JSON: $jsonPath")
$report.Add("- Destructive action: none")
$report.Add("")
$report.Add("## Exclusions")
$report.Add("")
$report.Add("Directory names excluded from hashing and comparison: $((@($ExcludedDirectoryNames) | Sort-Object) -join ', ')")
$report.Add("")
$report.Add("## Summary")
$report.Add("")
$report.Add("| Legacy workspace | Exists | Files checked | Exact matches | Same path different content | Content present elsewhere | Unique candidates |")
$report.Add("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
foreach ($result in $workspaceResults) {
    $report.Add("| $(ConvertTo-MarkdownCell $result.Path) | $($result.Exists) | $($result.TotalFiles) | $($result.ExactMatches.Count) | $($result.SamePathDifferentContent.Count) | $($result.ContentPresentElsewhere.Count) | $($result.UniqueCandidates.Count) |")
}
$report.Add("")
$report.Add("## Interpretation")
$report.Add("")
$report.Add("- `Exact matches`: same relative path and same SHA256 as the main workspace.")
$report.Add("- `Same path different content`: review before overwriting or deleting; these may contain local edits.")
$report.Add("- `Content present elsewhere`: byte-identical content exists in main under another path.")
$report.Add("- `Unique candidates`: no same-path match and no byte-identical content in main; migrate or archive before deleting.")
$report.Add("")

foreach ($result in $workspaceResults) {
    $report.Add("## Workspace: $($result.Path)")
    $report.Add("")
    if (-not $result.Exists) {
        $report.Add("Directory does not exist.")
        $report.Add("")
        continue
    }
    Add-FileRows -Report $report -Title "Unique candidates" -Rows $result.UniqueCandidates -MaxRows $MaxRowsPerSection
    Add-FileRows -Report $report -Title "Same path different content" -Rows $result.SamePathDifferentContent -MaxRows $MaxRowsPerSection
    Add-FileRows -Report $report -Title "Content present elsewhere" -Rows $result.ContentPresentElsewhere -MaxRows $MaxRowsPerSection
}

Set-Content -Path $reportPath -Value ($report -join [Environment]::NewLine) -Encoding UTF8

$jsonObject = [PSCustomObject]@{
    generated_at = (Get-Date).ToString("o")
    repository = $resolvedRepoPath
    report_path = $reportPath
    exclusions = @($ExcludedDirectoryNames) | Sort-Object
    workspaces = $workspaceResults
}
$jsonObject | ConvertTo-Json -Depth 20 | Set-Content -Path $jsonPath -Encoding UTF8

Write-Host "Legacy workspace audit report written to $reportPath"
Write-Host "Legacy workspace audit JSON written to $jsonPath"
