<#
.SYNOPSIS
  Runs the ZeroGravity Gemini browser bridge using Docker (default, zero host Python
  dependencies required) or natively on the host when -Native is specified.

.EXAMPLE
  # Sign in to a specific Google account (Docker + interactive noVNC browser tab on port 6080)
  .\services\browser_bridge\run_local.ps1 -Headed

.EXAMPLE
  # Sign in using a dedicated profile folder for a specific Google account
  .\services\browser_bridge\run_local.ps1 -ProfileDir "$HOME\.zg-work" -Headed

.EXAMPLE
  # Run headless in Docker reusing that signed-in Google account
  .\services\browser_bridge\run_local.ps1 -ProfileDir "$HOME\.zg-work"
#>
param(
    [string]$ProfileDir = "",
    [switch]$Headed,
    [int]$Port = 5000,
    [int]$NoVncPort = 6080,
    [switch]$Native,
    [string]$BrowserExecutable = $env:BROWSER_EXECUTABLE_PATH,
    [string]$Channel = $env:BROWSER_CHANNEL
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

if (-not $ProfileDir) {
    $ProfileDir = Join-Path $RepoRoot "data\browser_profile"
}

if (-not (Test-Path $ProfileDir)) {
    New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null
}
$ResolvedProfileDir = (Resolve-Path $ProfileDir).Path

$WorkspaceDir = Join-Path $RepoRoot "workspace"
if (-not (Test-Path $WorkspaceDir)) {
    New-Item -ItemType Directory -Force -Path $WorkspaceDir | Out-Null
}
$ResolvedWorkspaceDir = (Resolve-Path $WorkspaceDir).Path

# Default: Run inside Docker so all Python + Playwright + Chromium dependencies are self-contained
if (-not $Native -and -not $BrowserExecutable -and -not $Channel) {
    $headlessVal = if ($Headed) { "false" } else { "true" }
    $imageName = "zerogravity/gemini-bridge:local"

    Write-Host "Building Docker image $imageName ..." -ForegroundColor Cyan
    docker build -t $imageName $PSScriptRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Docker build failed for $imageName"
    }

    # Stop any existing gemini-bridge container using the same name/port
    docker rm -f gemini-bridge 2>$null | Out-Null

    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host "Starting Dockerized Gemini Bridge on http://localhost:$Port" -ForegroundColor Green
    Write-Host "  profile : $ResolvedProfileDir"
    Write-Host "  headless: $headlessVal"
    if ($Headed) {
        $vncUrl = "http://localhost:$NoVncPort/vnc.html?autoconnect=true&resize=scale"
        Write-Host "  login UI: $vncUrl" -ForegroundColor Yellow
        Write-Host "  -> Sign in to your Google account in the browser window that opens," -ForegroundColor Yellow
        Write-Host "     then press Ctrl+C here when finished to save the session." -ForegroundColor Yellow
        Start-Job -ScriptBlock {
            param($u)
            Start-Sleep -Seconds 3
            Start-Process $u
        } -ArgumentList $vncUrl | Out-Null
    }
    Write-Host "======================================================================" -ForegroundColor Cyan

    $dockerArgs = @(
        "run", "--rm", "-it",
        "--name", "gemini-bridge",
        "-p", "${Port}:5000",
        "-p", "${NoVncPort}:6080",
        "-e", "BROWSER_PROFILE_DIR=/data/browser_profile",
        "-e", "ZEROGRAVITY_HEADLESS=$headlessVal",
        "-e", "PORT=5000",
        "-e", "NOVNC_PORT=6080",
        "-v", "${ResolvedProfileDir}:/data/browser_profile",
        "-v", "${ResolvedWorkspaceDir}:/workspace"
    )
    if (Test-Path (Join-Path $RepoRoot "docker-compose.yml")) {
        $netExists = docker network ls --filter "name=zerogravity-net" -q
        if ($netExists) {
            $dockerArgs += @("--network", "0g_zerogravity-net")
        }
    }
    $dockerArgs += $imageName

    & docker @dockerArgs
    exit $LASTEXITCODE
}

# Optional Native Host Mode (only when -Native, -BrowserExecutable, or -Channel is passed)
Push-Location $PSScriptRoot
try {
    $venv = Join-Path $PSScriptRoot ".venv"
    $python = Join-Path $venv "Scripts\python.exe"

    if (-not (Test-Path $python)) {
        Write-Host "Creating virtual environment in $venv ..."
        python -m venv $venv
        if (-not (Test-Path $python)) {
            throw "Local Python installation not found (Windows Store alias detected). Run without -Native to use Docker for all dependencies."
        }
        & $python -m pip install --upgrade pip
        & $python -m pip install -r requirements.txt
    }

    if (-not $BrowserExecutable -and -not $Channel) {
        & $python -m playwright install chromium
    }

    if ($BrowserExecutable -and -not (Test-Path $BrowserExecutable)) {
        throw "Browser executable not found: $BrowserExecutable"
    }

    $env:BROWSER_PROFILE_DIR = $ResolvedProfileDir
    $env:BROWSER_EXECUTABLE_PATH = $BrowserExecutable
    $env:BROWSER_CHANNEL = $Channel
    $env:ZEROGRAVITY_HEADLESS = if ($Headed) { "false" } else { "true" }
    $env:PORT = "$Port"

    Write-Host "Starting Native Gemini bridge on http://localhost:$Port"
    Write-Host "  profile : $ResolvedProfileDir"
    Write-Host "  browser : $(if ($BrowserExecutable) { $BrowserExecutable } elseif ($Channel) { "channel=$Channel" } else { 'bundled Chromium' })"
    Write-Host "  headless: $($env:ZEROGRAVITY_HEADLESS)"

    & $python server.py
} finally {
    Pop-Location
}
