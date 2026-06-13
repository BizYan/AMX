param(
  [string]$RepoPath = (Get-Location).Path,
  [string]$OwnerRepo,
  [string]$Branch,
  [string]$BaseRef = 'main',
  [string]$CommitMessage,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

function Invoke-GhJson {
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$Arguments,
    [object]$Payload = $null,
    [switch]$AllowFailure
  )

  if ($null -eq $Payload) {
    $previousErrorActionPreference = $ErrorActionPreference
    if ($AllowFailure) { $ErrorActionPreference = 'Continue' }
    $output = & gh @Arguments 2>&1
    $ErrorActionPreference = $previousErrorActionPreference
  } else {
    $json = $Payload | ConvertTo-Json -Depth 20
    $previousErrorActionPreference = $ErrorActionPreference
    if ($AllowFailure) { $ErrorActionPreference = 'Continue' }
    $output = $json | & gh @Arguments 2>&1
    $ErrorActionPreference = $previousErrorActionPreference
  }

  if ($LASTEXITCODE -ne 0 -and -not $AllowFailure) {
    throw ($output -join [Environment]::NewLine)
  }

  return @{
    ExitCode = $LASTEXITCODE
    Output = ($output -join [Environment]::NewLine)
  }
}

function Get-OriginOwnerRepo {
  $remote = (git remote get-url origin).Trim()
  if ($remote -match 'github\.com[:/](?<owner>[^/]+)/(?<repo>[^/.]+)(\.git)?$') {
    return "$($Matches.owner)/$($Matches.repo)"
  }
  throw 'OwnerRepo was not supplied and origin is not a recognizable GitHub URL.'
}

function Get-CurrentBranch {
  $current = (git branch --show-current).Trim()
  if (-not $current) {
    throw 'Branch was not supplied and the current HEAD is detached.'
  }
  return $current
}

$resolvedRepo = (Resolve-Path -LiteralPath $RepoPath).Path
Set-Location $resolvedRepo

if (-not $OwnerRepo) {
  $OwnerRepo = Get-OriginOwnerRepo
}

if (-not $Branch) {
  $Branch = Get-CurrentBranch
}

if (-not $CommitMessage) {
  $CommitMessage = (git log -1 --pretty=%B).Trim()
}

$changedFiles = @(git diff --name-status "$BaseRef..HEAD")
if ($changedFiles.Count -eq 0) {
  throw "No changed files found between $BaseRef and HEAD."
}

if ($DryRun) {
  [pscustomobject]@{
    mode = 'dry-run'
    repo_path = $resolvedRepo
    owner_repo = $OwnerRepo
    branch = $Branch
    base_ref = $BaseRef
    local_head = (git rev-parse HEAD).Trim()
    commit_message = $CommitMessage
    changed_files = $changedFiles
  } | ConvertTo-Json -Depth 5
  exit 0
}

$baseRefResponse = Invoke-GhJson -Arguments @('api', "repos/$OwnerRepo/git/ref/heads/$BaseRef")
$baseSha = (($baseRefResponse.Output | ConvertFrom-Json).object.sha)
if (-not $baseSha) {
  throw "Unable to resolve remote base ref $BaseRef for $OwnerRepo."
}

$baseCommitResponse = Invoke-GhJson -Arguments @('api', "repos/$OwnerRepo/git/commits/$baseSha")
$baseTreeSha = (($baseCommitResponse.Output | ConvertFrom-Json).tree.sha)
if (-not $baseTreeSha) {
  throw "Unable to resolve remote base tree for $baseSha."
}

$treeEntries = @()
foreach ($line in $changedFiles) {
  if (-not $line.Trim()) { continue }

  $parts = $line -split "`t"
  $status = $parts[0]
  $path = if ($status.StartsWith('R') -and $parts.Length -ge 3) { $parts[2] } else { $parts[1] }
  $repoRelativePath = $path -replace '\\', '/'

  if ($status.StartsWith('D')) {
    $treeEntries += [ordered]@{
      path = $repoRelativePath
      mode = '100644'
      type = 'blob'
      sha = $null
    }
    continue
  }

  $absolutePath = Join-Path $resolvedRepo $path
  if (-not (Test-Path -LiteralPath $absolutePath)) {
    throw "Changed file not found: $absolutePath"
  }

  $blobPayload = @{
    content = [Convert]::ToBase64String([IO.File]::ReadAllBytes($absolutePath))
    encoding = 'base64'
  }
  $blobResponse = Invoke-GhJson -Arguments @('api', "repos/$OwnerRepo/git/blobs", '--method', 'POST', '--input', '-') -Payload $blobPayload
  $blobSha = (($blobResponse.Output | ConvertFrom-Json).sha)
  if (-not $blobSha) {
    throw "Failed to create blob for $repoRelativePath."
  }

  $treeEntries += [ordered]@{
    path = $repoRelativePath
    mode = '100644'
    type = 'blob'
    sha = $blobSha
  }
}

$treePayload = @{
  base_tree = $baseTreeSha
  tree = $treeEntries
}
$treeResponse = Invoke-GhJson -Arguments @('api', "repos/$OwnerRepo/git/trees", '--method', 'POST', '--input', '-') -Payload $treePayload
$treeSha = (($treeResponse.Output | ConvertFrom-Json).sha)
if (-not $treeSha) {
  throw 'Failed to create Git tree.'
}

$commitPayload = @{
  message = $CommitMessage
  tree = $treeSha
  parents = @($baseSha)
}
$commitResponse = Invoke-GhJson -Arguments @('api', "repos/$OwnerRepo/git/commits", '--method', 'POST', '--input', '-') -Payload $commitPayload
$commitSha = (($commitResponse.Output | ConvertFrom-Json).sha)
if (-not $commitSha) {
  throw 'Failed to create Git commit.'
}

$refResponse = Invoke-GhJson -Arguments @('api', "repos/$OwnerRepo/git/ref/heads/$Branch") -AllowFailure
if ($refResponse.ExitCode -eq 0) {
  $null = Invoke-GhJson -Arguments @('api', "repos/$OwnerRepo/git/refs/heads/$Branch", '--method', 'PATCH', '--input', '-') -Payload @{
    sha = $commitSha
    force = $false
  }
} else {
  $null = Invoke-GhJson -Arguments @('api', "repos/$OwnerRepo/git/refs", '--method', 'POST', '--input', '-') -Payload @{
    ref = "refs/heads/$Branch"
    sha = $commitSha
  }
}

[pscustomobject]@{
  mode = 'published'
  owner_repo = $OwnerRepo
  branch = $Branch
  base_ref = $BaseRef
  base_sha = $baseSha
  commit_sha = $commitSha
  changed_files = $treeEntries.Count
} | ConvertTo-Json -Depth 5
