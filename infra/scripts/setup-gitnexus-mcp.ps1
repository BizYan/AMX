param(
    [string]$RepoPath = "C:\amx\AMX-main",
    [string]$NpmRegistry = "https://registry.npmmirror.com",
    [switch]$SkipAnalyze
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is required before GitNexus MCP can be installed."
}

npm install -g gitnexus@latest --registry=$NpmRegistry

if (-not $SkipAnalyze) {
    Push-Location $RepoPath
    try {
        gitnexus analyze --index-only
    }
    finally {
        Pop-Location
    }
}

$codexConfig = Join-Path $env:USERPROFILE ".codex\config.toml"
$codexDir = Split-Path $codexConfig
New-Item -ItemType Directory -Force -Path $codexDir | Out-Null

$block = @"

[mcp_servers.gitnexus]
command = "npx"
args = ["-y", "--registry=$NpmRegistry", "gitnexus@latest", "mcp"]
"@

$current = if (Test-Path $codexConfig) { Get-Content -Raw $codexConfig } else { "" }
if ($current -notmatch '\[mcp_servers\.gitnexus\]') {
    Add-Content -Path $codexConfig -Value $block
}

Write-Host "GitNexus MCP is configured for Codex at $codexConfig"
