<#
.SYNOPSIS
  Runs the ZeroGravity Gemini bridge natively on Windows (outside Docker),
  so it can drive a host browser such as Brave, Chrome or Edge.

.EXAMPLE
  # Brave, visible window (first-time Google sign-in)
  .\run_local.ps1 -BrowserExecutable "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" -Headed

.EXAMPLE
  # Installed Chrome via Playwright channel, headless
  .\run_local.ps1 -Channel chrome

.NOTES
  Then point the dockerized router at the host bridge, in .env:
    ZEROGRAVITY_BROWSER_URL=http://host.docker.internal:5000
  and start only the other services:
    docker compose up -d quota-router open-webui
#>
param(
    [string]$BrowserExecutable = $env:BROWSER_EXECUTABLE_PATH,
    [string]$Channel = $env:BROWSER_CHANNEL,
    # Use a dedicated profile. Pointing at your everyday browser's "User Data" folder
    # fails while that browser is open (profile lock).
    [string]$ProfileDir = (Join-Path $HOME ".zerogravity-profile"),
    [switch]$Headed,
    [int]$Port = 5000
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venv = Join-Path $PSScriptRoot ".venv"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment in $venv ..."
    python -m venv $venv
    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements.txt
}

# Bundled Chromium is only needed when no host browser is configured
if (-not $BrowserExecutable -and -not $Channel) {
    & $python -m playwright install chromium
}

if ($BrowserExecutable -and -not (Test-Path $BrowserExecutable)) {
    throw "Browser executable not found: $BrowserExecutable"
}

$env:BROWSER_PROFILE_DIR = $ProfileDir
$env:BROWSER_EXECUTABLE_PATH = $BrowserExecutable
$env:BROWSER_CHANNEL = $Channel
$env:ZEROGRAVITY_HEADLESS = if ($Headed) { "false" } else { "true" }
$env:PORT = "$Port"

Write-Host "Starting Gemini bridge on http://localhost:$Port"
Write-Host "  profile : $ProfileDir"
Write-Host "  browser : $(if ($BrowserExecutable) { $BrowserExecutable } elseif ($Channel) { "channel=$Channel" } else { 'bundled Chromium' })"
Write-Host "  headless: $($env:ZEROGRAVITY_HEADLESS)"

& $python server.py

