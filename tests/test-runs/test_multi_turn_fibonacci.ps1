<#
.SYNOPSIS
  Multi-turn (2 turns) test for ZeroGravity:
  Prompts Gemini to generate at least 2 JavaScript (.js) files on Turn 1,
  and at least 2 new JavaScript (.js) files on Turn 2.

.DESCRIPTION
  Turn 1: Creates 'src/fibonacci.js' (core math) and 'src/cli.js' (CLI runner)
  Turn 2: Follow-up in the same chat session creating 'src/memoizedFibonacci.js' (cache)
          and 'src/benchmark.js' (performance comparison)

.EXAMPLE
  .\test_multi_turn_fibonacci.ps1 -RouterUrl "http://localhost:8000"
#>
param(
    [string]$RouterUrl = "http://localhost:8000",
    [string]$WorkspaceDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $WorkspaceDir) {
    if (Test-Path "$PSScriptRoot\..\..\workspace") {
        $WorkspaceDir = (Resolve-Path "$PSScriptRoot\..\..\workspace").Path
    } else {
        $WorkspaceDir = "$PSScriptRoot\workspace"
    }
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " ZeroGravity Multi-Turn Test: Fibonacci JS Generator" -ForegroundColor Cyan
Write-Host " Target Router: $RouterUrl" -ForegroundColor Cyan
Write-Host " Target Workspace: $WorkspaceDir" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Check Router Health
try {
    $health = Invoke-RestMethod -Uri "$RouterUrl/healthz" -Method Get -TimeoutSec 5
    Write-Host "[1/4] Router is reachable. Status: $($health.status), Local AI: $($health.local_ai_enabled)" -ForegroundColor Green
} catch {
    Write-Error "Cannot reach router at $RouterUrl. Ensure the stack or local router is running."
    exit 1
}

# -------------------------------------------------------------
# Turn 1: Initial Prompt
# -------------------------------------------------------------
Write-Host "`n----------------------------------------------------------" -ForegroundColor Yellow
Write-Host ">>> TURN 1: Requesting core Fibonacci library & CLI runner" -ForegroundColor Yellow
Write-Host "----------------------------------------------------------" -ForegroundColor Yellow

$turn1Prompt = @'
Build a modular Node.js Fibonacci project. You MUST generate at least two separate JavaScript (.js) files:
1. File: src/fibonacci.js
   - Export an iterative function `fibonacci(n)` and a recursive function `fibonacciRecursive(n)`.
   - Include argument validation (throw Error if n < 0 or not an integer).
2. File: src/cli.js
   - Import `fibonacci` from `./fibonacci.js`.
   - Read the number `n` from process.argv (default to 10 if omitted) and print the sequence.

Declare each file with a clear "File: <path>" header immediately preceding its code block.
'@

$turn1Body = @{
    model = "zerogravity"
    messages = @(
        @{ role = "user"; content = $turn1Prompt }
    )
} | ConvertTo-Json -Depth 5

$turn1Start = Get-Date
$turn1Resp = Invoke-RestMethod -Uri "$RouterUrl/v1/chat/completions" -Method Post -Body $turn1Body -ContentType "application/json" -TimeoutSec 600
$turn1Duration = [Math]::Round(((Get-Date) - $turn1Start).TotalSeconds, 1)

$turn1Reply = $turn1Resp.choices[0].message.content
Write-Host "Turn 1 finished in ${turn1Duration}s" -ForegroundColor Green
Write-Host "Assistant Reply Summary:" -ForegroundColor Gray
Write-Host ($turn1Reply.Substring(0, [Math]::Min(350, $turn1Reply.Length)) + "...")

# Verify Turn 1 JS files in workspace
$turn1Files = Get-ChildItem -Path $WorkspaceDir -Recurse -Filter "*.js" -ErrorAction SilentlyContinue
Write-Host "`nWorkspace JS files after Turn 1 ($($turn1Files.Count) found):" -ForegroundColor Cyan
$turn1Files | ForEach-Object { Write-Host "  - $($_.FullName)" -ForegroundColor White }

if ($turn1Files.Count -lt 2) {
    Write-Warning "Turn 1 produced fewer than 2 JS files. Found: $($turn1Files.Count)"
} else {
    Write-Host "SUCCESS: Turn 1 produced $($turn1Files.Count) JS files." -ForegroundColor Green
}

# -------------------------------------------------------------
# Turn 2: Follow-up Prompt in the same conversation
# -------------------------------------------------------------
Write-Host "`n----------------------------------------------------------" -ForegroundColor Yellow
Write-Host ">>> TURN 2: Requesting memoization & benchmark modules" -ForegroundColor Yellow
Write-Host "----------------------------------------------------------" -ForegroundColor Yellow

$turn2Prompt = @'
Great! Now expand our Fibonacci project by creating at least two NEW separate JavaScript (.js) files:
1. File: src/memoizedFibonacci.js
   - Export `memoizedFibonacci(n)` using a Map or closure cache.
   - Also export a generator function `fibonacciSequence(limit)`.
2. File: src/benchmark.js
   - Import `fibonacci` from `./fibonacci.js` and `memoizedFibonacci` from `./memoizedFibonacci.js`.
   - Measure and compare the execution time of calculating the 40th Fibonacci number using console.time / console.timeEnd.

Declare each file with a clear "File: <path>" header immediately preceding its code block.
'@

$turn2Body = @{
    model = "zerogravity"
    messages = @(
        @{ role = "user"; content = $turn1Prompt },
        @{ role = "assistant"; content = $turn1Reply },
        @{ role = "user"; content = $turn2Prompt }
    )
} | ConvertTo-Json -Depth 5

$turn2Start = Get-Date
$turn2Resp = Invoke-RestMethod -Uri "$RouterUrl/v1/chat/completions" -Method Post -Body $turn2Body -ContentType "application/json" -TimeoutSec 600
$turn2Duration = [Math]::Round(((Get-Date) - $turn2Start).TotalSeconds, 1)

$turn2Reply = $turn2Resp.choices[0].message.content
Write-Host "Turn 2 finished in ${turn2Duration}s" -ForegroundColor Green
Write-Host "Assistant Reply Summary:" -ForegroundColor Gray
Write-Host ($turn2Reply.Substring(0, [Math]::Min(350, $turn2Reply.Length)) + "...")

# Verify All JS files in workspace
$allFiles = Get-ChildItem -Path $WorkspaceDir -Recurse -Filter "*.js" -ErrorAction SilentlyContinue
Write-Host "`nTotal workspace JS files after Turn 2 ($($allFiles.Count) found):" -ForegroundColor Cyan
$allFiles | ForEach-Object { Write-Host "  - $($_.FullName)" -ForegroundColor White }

# Check .gemini-history
$historyDir = Join-Path $WorkspaceDir ".gemini-history"
if (Test-Path $historyDir) {
    Write-Host "`nAudit History Log (.gemini-history):" -ForegroundColor Cyan
    Get-ChildItem -Path "$historyDir\turns" -Directory | ForEach-Object {
        Write-Host "  Turn Log: $($_.Name)" -ForegroundColor Gray
    }
}

if ($allFiles.Count -ge 4) {
    Write-Host "`n🎉 MULTI-TURN TEST PASSED: Generated $($allFiles.Count) JavaScript files across 2 turns." -ForegroundColor Green
} else {
    Write-Warning "`n⚠️ Expected at least 4 JS files total (>=2 per turn), found: $($allFiles.Count)"
}

