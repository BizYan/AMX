[CmdletBinding()]
param(
    [switch]$AllowDirty,
    [switch]$AllowUnmergedBranches,
    [switch]$AllowMissingReleaseTag,
    [string]$EvidencePath
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Invoke-Git {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & git -C $repoRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $output"
    }
    return @($output)
}

$failures = [System.Collections.Generic.List[string]]::new()
$evidence = [ordered]@{
    checked_at_utc = [DateTime]::UtcNow.ToString("o")
    repository = $repoRoot
}

$status = Invoke-Git -Arguments @("status", "--porcelain")
$evidence.clean_worktree = $status.Count -eq 0
if (-not $evidence.clean_worktree -and -not $AllowDirty) {
    $failures.Add("Working tree is not clean.")
}

$tags = Invoke-Git -Arguments @("tag", "--points-at", "HEAD")
$releaseTags = @($tags | Where-Object { $_ -match "^v\d+\.\d+\.\d+$" })
$evidence.release_tags_at_head = $releaseTags
if ($releaseTags.Count -eq 0 -and -not $AllowMissingReleaseTag) {
    $failures.Add("HEAD does not have a semantic release tag.")
}

$unmerged = Invoke-Git -Arguments @("branch", "--no-merged", "HEAD", "--format=%(refname:short)")
$evidence.unmerged_local_branches = @($unmerged)
if ($unmerged.Count -gt 0 -and -not $AllowUnmergedBranches) {
    $failures.Add("Local branches contain commits not merged into HEAD.")
}

$requiredFiles = @(
    ".github/workflows/ci.yml",
    ".github/workflows/deploy-production.yml",
    ".github/workflows/release.yml",
    "docs/runbooks/release-management.md",
    "infra/deploy/health-check.sh",
    "infra/deploy/authenticated-smoke.sh",
    "infra/deploy/deployment-evidence.sh",
    "infra/deploy/validate-runtime-security.sh",
    "apps/web/tests/e2e/playwright/production-smoke.spec.ts"
)
$missingFiles = @($requiredFiles | Where-Object { -not (Test-Path (Join-Path $repoRoot $_)) })
$evidence.missing_required_files = $missingFiles
if ($missingFiles.Count -gt 0) {
    $failures.Add("Required delivery files are missing: $($missingFiles -join ', ')")
}

$requiredWorkflowMarkers = [ordered]@{
    ".github/workflows/ci.yml" = @("workflow_call:", "Web deterministic E2E", "deterministic-regression.spec.ts")
    ".github/workflows/release.yml" = @("Verify repository delivery state", "Release quality gates", "uses: ./.github/workflows/ci.yml")
    ".github/workflows/deploy-production.yml" = @("Authenticated production smoke", "authenticated-smoke.sh", "Verify deployment provenance", "deployment-evidence.sh")
}
$missingWorkflowMarkers = [System.Collections.Generic.List[string]]::new()
foreach ($workflow in $requiredWorkflowMarkers.Keys) {
    $workflowPath = Join-Path $repoRoot $workflow
    if (-not (Test-Path $workflowPath)) {
        continue
    }
    $workflowContent = Get-Content -LiteralPath $workflowPath -Raw
    foreach ($marker in $requiredWorkflowMarkers[$workflow]) {
        if (-not $workflowContent.Contains($marker)) {
            $missingWorkflowMarkers.Add("${workflow}: ${marker}")
        }
    }
}
$evidence.missing_workflow_markers = @($missingWorkflowMarkers)
if ($missingWorkflowMarkers.Count -gt 0) {
    $failures.Add("Required workflow gates are missing: $($missingWorkflowMarkers -join ', ')")
}

$evidence.ready = $failures.Count -eq 0
$evidence.failures = @($failures)
$evidenceJson = $evidence | ConvertTo-Json -Depth 5
$evidenceJson

if ($EvidencePath) {
    $resolvedEvidencePath = Join-Path $repoRoot $EvidencePath
    $evidenceDirectory = Split-Path $resolvedEvidencePath -Parent
    New-Item -ItemType Directory -Force -Path $evidenceDirectory | Out-Null
    Set-Content -LiteralPath $resolvedEvidencePath -Value $evidenceJson -Encoding utf8
}

if ($failures.Count -gt 0) {
    exit 1
}
