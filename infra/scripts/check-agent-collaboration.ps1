param(
    [string]$RepoPath = "C:\amx\ConsultantAIP-main",
    [string]$BaseRef = "main",
    [string]$ReportsDir = "C:\amx\reports",
    [switch]$RefreshIfStale,
    [switch]$SkipDetectChanges
)

$ErrorActionPreference = "Stop"

function Invoke-Captured {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $Command @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    [PSCustomObject]@{
        Command = "$Command $($Arguments -join ' ')"
        ExitCode = $exitCode
        Output = ($output | Out-String).Trim()
    }
}

if (-not (Test-Path $RepoPath)) {
    throw "Repository path does not exist: $RepoPath"
}

foreach ($command in @("git", "gitnexus")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command is required for collaboration checks."
    }
}

New-Item -ItemType Directory -Force -Path $ReportsDir | Out-Null

Push-Location $RepoPath
try {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $reportPath = Join-Path $ReportsDir "agent-collaboration-health-$timestamp.md"

    $workspaceChecks = @(
        "C:\amx\ConsultantAIP-main",
        "C:\amx\ConsultantAIP-codex",
        "C:\amx\ConsultantAIP-antigravity",
        "C:\amx\ConsultantAIP-claude",
        "C:\amx\reports"
    ) | ForEach-Object {
        [PSCustomObject]@{
            Path = $_
            Exists = Test-Path $_
        }
    }

    $gitBranch = Invoke-Captured git @("branch", "--show-current")
    $gitCommit = Invoke-Captured git @("log", "-1", "--oneline")
    $gitStatus = Invoke-Captured git @("status", "-sb")
    $gitnexusVersion = Invoke-Captured gitnexus @("--version")
    $gitnexusStatus = Invoke-Captured gitnexus @("status")

    if ($RefreshIfStale -and $gitnexusStatus.Output -notmatch "up-to-date") {
        $gitnexusRefresh = Invoke-Captured gitnexus @("analyze", "--index-only")
        $gitnexusStatus = Invoke-Captured gitnexus @("status")
    }
    else {
        $gitnexusRefresh = $null
    }

    if (-not $SkipDetectChanges) {
        $gitnexusChanges = Invoke-Captured gitnexus @("detect-changes", "--scope", "all", "--base-ref", $BaseRef, "--repo", $RepoPath)
    }
    else {
        $gitnexusChanges = $null
    }

    $ghStatus = if (Get-Command gh -ErrorAction SilentlyContinue) {
        Invoke-Captured gh @("auth", "status")
    }
    else {
        [PSCustomObject]@{
            Command = "gh auth status"
            ExitCode = 127
            Output = "GitHub CLI is not installed or not on PATH."
        }
    }

    $report = @()
    $report += "# Agent Collaboration Health"
    $report += ""
    $report += "- Generated: $(Get-Date -Format o)"
    $report += "- Repository: $RepoPath"
    $report += "- Base ref: $BaseRef"
    $report += ""
    $report += "## Workspace Layout"
    $report += ""
    foreach ($item in $workspaceChecks) {
        $mark = if ($item.Exists) { "OK" } else { "MISSING" }
        $report += "- [$mark] $($item.Path)"
    }
    $report += ""

    foreach ($section in @(
        @{ Title = "Git Branch"; Result = $gitBranch },
        @{ Title = "Git Commit"; Result = $gitCommit },
        @{ Title = "Git Status"; Result = $gitStatus },
        @{ Title = "GitHub Auth"; Result = $ghStatus },
        @{ Title = "GitNexus Version"; Result = $gitnexusVersion },
        @{ Title = "GitNexus Status"; Result = $gitnexusStatus },
        @{ Title = "GitNexus Refresh"; Result = $gitnexusRefresh },
        @{ Title = "GitNexus Detect Changes"; Result = $gitnexusChanges }
    )) {
        if ($null -eq $section.Result) {
            continue
        }
        $report += "## $($section.Title)"
        $report += ""
        $report += "Command: " + '``' + $section.Result.Command + '``'
        $report += ""
        $report += "Exit code: " + '``' + $section.Result.ExitCode + '``'
        $report += ""
        $report += '```text'
        $report += $section.Result.Output
        $report += '```'
        $report += ""
    }

    Set-Content -Path $reportPath -Value ($report -join [Environment]::NewLine) -Encoding UTF8
    Write-Host "Collaboration health report written to $reportPath"
}
finally {
    Pop-Location
}
