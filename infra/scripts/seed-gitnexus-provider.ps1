param(
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [Parameter(Mandatory = $true)][string]$Email,
    [Parameter(Mandatory = $true)][string]$Password,
    [Parameter(Mandatory = $true)][string]$GitNexusUrl,
    [Parameter(Mandatory = $true)][string]$GitNexusApiKey,
    [string]$ProviderName = "GitNexus",
    [string]$RepositoryFullName = "BizYan/AMX",
    [string]$RefreshPolicy = "main-and-pr",
    [string]$HealthPath = "/api/health",
    [int]$TimeoutSeconds = 30,
    [switch]$RunConnectionTest
)

$ErrorActionPreference = "Stop"

function Assert-ProductionSecret {
    param([string]$Secret)

    $unsafeValues = @("", "mock", "sandbox", "placeholder", "test", "test-key", "test_api_key", "demo")
    if ($unsafeValues -contains $Secret.Trim().ToLowerInvariant()) {
        throw "GitNexusApiKey must be a real internal service key, not a sandbox/mock/test value."
    }
}

function Invoke-AmxJson {
    param(
        [string]$Method,
        [string]$Path,
        [object]$Body,
        [string]$Token
    )

    $headers = @{ "Content-Type" = "application/json" }
    if ($Token) {
        $headers["Authorization"] = "Bearer $Token"
    }

    $uri = "$($BaseUrl.TrimEnd('/'))/$($Path.TrimStart('/'))"
    $json = $null
    if ($null -ne $Body) {
        $json = $Body | ConvertTo-Json -Depth 20
    }

    Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers -Body $json
}

function ConvertTo-SafeProviderOutput {
    param([object]$Provider)

    $safe = $Provider | ConvertTo-Json -Depth 20 | ConvertFrom-Json
    foreach ($configProperty in @("config", "config_json")) {
        if ($safe.PSObject.Properties.Name -contains $configProperty) {
            foreach ($secretProperty in @("api_key", "service_key", "token", "access_token", "secret")) {
                if ($safe.$configProperty.PSObject.Properties.Name -contains $secretProperty) {
                    $safe.$configProperty.$secretProperty = "***"
                }
            }
        }
    }
    $safe
}

Assert-ProductionSecret -Secret $GitNexusApiKey

$login = Invoke-AmxJson -Method Post -Path "/identity/auth/login" -Body @{
    email = $Email
    password = $Password
}

$token = $login.access_token
if (-not $token) {
    throw "Login did not return an access token"
}

$provider = Invoke-AmxJson -Method Post -Path "/providers" -Token $token -Body @{
    name = $ProviderName
    provider_type = "gitnexus"
    config = @{
        endpoint = $GitNexusUrl.TrimEnd("/")
        base_url = $GitNexusUrl.TrimEnd("/")
        service_key = $GitNexusApiKey
        health_path = $HealthPath
        timeout = $TimeoutSeconds
        allowed_repositories = @($RepositoryFullName)
        repository = $RepositoryFullName
        refresh_policy = $RefreshPolicy
        mode = "production"
    }
    capabilities = @{
        commits = @{ enabled = $true }
        issues = @{ enabled = $true }
        code_index = @{ enabled = $true }
    }
}

$result = @{
    provider = ConvertTo-SafeProviderOutput -Provider $provider
}

if ($RunConnectionTest) {
    $providerId = $provider.id
    if (-not $providerId) {
        throw "Provider registration response did not include provider id; cannot run connection test."
    }

    $testResult = Invoke-AmxJson -Method Post -Path "/providers/$providerId/test" -Token $token -Body @{
        capability_type = "health"
        params = @{
            repo_url = "https://github.com/$RepositoryFullName"
            limit = 5
        }
        allow_sandbox = $false
    }
    $result["connection_test"] = $testResult
}

$result | ConvertTo-Json -Depth 20
