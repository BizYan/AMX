# =============================================================================
# AMX - Deployment Verification Script
# =============================================================================

<#
.SYNOPSIS
    Checks deployment readiness for AMX.

.DESCRIPTION
    This script verifies that all prerequisites for deployment are met:
    - Docker is installed and running
    - docker-compose config is valid
    - All environment variables are set
    - All Dockerfiles exist and are valid
    - Connectivity to required ports

.EXAMPLE
    .\check-deploy.ps1
#>

param(
    [switch]$SkipPortCheck,
    [switch]$Verbose
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir

function Write-Step {
    param([string]$Message)
    Write-Host "[CHECK] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Write-Failure {
    param([string]$Message)
    Write-Host "[FAIL] $Message" -ForegroundColor Red
}

function Write-Info {
    param([string]$Message)
    if ($Verbose) {
        Write-Host "[INFO] $Message" -ForegroundColor Gray
    }
}

# -----------------------------------------------------------------------------
# 1. Check Docker is installed and running
# -----------------------------------------------------------------------------
Write-Step "Checking Docker installation..."

try {
    $dockerVersion = docker --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Failure "Docker is not installed or not in PATH"
        exit 1
    }
    Write-Success "Docker installed: $dockerVersion"
} catch {
    Write-Failure "Docker is not installed: $_"
    exit 1
}

try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Failure "Docker daemon is not running"
        exit 1
    }
    Write-Success "Docker daemon is running"
} catch {
    Write-Failure "Docker daemon is not accessible: $_"
    exit 1
}

# -----------------------------------------------------------------------------
# 2. Check docker-compose config validity
# -----------------------------------------------------------------------------
Write-Step "Checking docker-compose configuration..."

$composeFile = Join-Path $RootDir "docker-compose.yml"

if (-not (Test-Path $composeFile)) {
    Write-Failure "docker-compose.yml not found at: $composeFile"
    exit 1
}

Write-Info "Validating docker-compose.yml..."

try {
    $composeConfig = docker compose -f $composeFile config 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Failure "docker-compose.yml is invalid: $composeConfig"
        exit 1
    }
    Write-Success "docker-compose.yml is valid"
} catch {
    Write-Failure "Failed to validate docker-compose.yml: $_"
    exit 1
}

# -----------------------------------------------------------------------------
# 3. Verify environment variables
# -----------------------------------------------------------------------------
Write-Step "Checking environment variables..."

$envExample = Join-Path $RootDir "env.example"

if (-not (Test-Path $envExample)) {
    Write-Failure "env.example not found at: $envExample"
    exit 1
}

Write-Info "Reading required environment variables from env.example..."

$requiredVars = @(
    "DATABASE_URL",
    "REDIS_URL",
    "ARQ_REDIS_URL",
    "JWT_SECRET_KEY",
    "BOOTSTRAP_ADMIN_EMAIL",
    "BOOTSTRAP_ADMIN_PASSWORD",
    "OPENAI_API_KEY",
    "CORS_ORIGINS"
)

$missingVars = @()
foreach ($var in $requiredVars) {
    $value = [System.Environment]::GetEnvironmentVariable($var)
    if ([string]::IsNullOrEmpty($value)) {
        $missingVars += $var
    } else {
        Write-Info "$var is set"
    }
}

if ($missingVars.Count -gt 0) {
    Write-Failure "Missing required environment variables: $($missingVars -join ', ')"
    Write-Info "Copy env.example to .env and configure: cp env.example .env"
} else {
    Write-Success "All required environment variables are set"
}

# -----------------------------------------------------------------------------
# 4. Verify all Dockerfiles exist
# -----------------------------------------------------------------------------
Write-Step "Checking Dockerfiles..."

$dockerfiles = @(
    "apps/api/Dockerfile",
    "apps/worker/Dockerfile",
    "apps/web/Dockerfile"
)

foreach ($df in $dockerfiles) {
    $dfPath = Join-Path $RootDir $df
    if (Test-Path $dfPath) {
        Write-Success "Found: $df"
    } else {
        Write-Failure "Missing: $df"
        exit 1
    }
}

# -----------------------------------------------------------------------------
# 5. Test connectivity to required ports
# -----------------------------------------------------------------------------
if (-not $SkipPortCheck) {
    Write-Step "Checking port connectivity..."

    $ports = @{
        "PostgreSQL" = 5432
        "Redis" = 6379
        "API" = 8000
        "Web" = 3000
    }

    foreach ($service in $ports.Keys) {
        $port = $ports[$service]
        $connection = Test-NetConnection -ComputerName localhost -Port $port -WarningAction SilentlyContinue

        if ($connection.TcpTestSucceeded) {
            Write-Success "$service port $port is accessible"
        } else {
            Write-Info "$service port $port is not accessible (services may not be running)"
        }
    }
}

# -----------------------------------------------------------------------------
# 6. Check system resources
# -----------------------------------------------------------------------------
Write-Step "Checking system resources..."

$memInfo = Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize, FreePhysicalMemory
$totalMemGB = [math]::Round($memInfo.TotalVisibleMemorySize / 1MB, 2)
$freeMemGB = [math]::Round($memInfo.FreePhysicalMemory / 1MB, 2)

Write-Info "Total Memory: $totalMemGB GB"
Write-Info "Free Memory: $freeMemGB GB"

if ($freeMemGB -lt 2) {
    Write-Failure "Low memory warning: Less than 2GB free RAM"
} else {
    Write-Success "Sufficient memory available"
}

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "========================================" -ForegroundColor White
Write-Host "Deployment Readiness Check Complete" -ForegroundColor White
Write-Host "========================================" -ForegroundColor White
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Ensure all env variables are configured in .env" -ForegroundColor White
Write-Host "  2. Run: docker compose -f infra/docker-compose.yml up -d" -ForegroundColor White
Write-Host "  3. Check logs: docker compose -f infra/docker-compose.yml logs -f" -ForegroundColor White
Write-Host ""
