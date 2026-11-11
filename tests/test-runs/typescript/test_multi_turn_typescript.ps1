<#
.SYNOPSIS
  Multi-turn (2 turns) TypeScript PriorityQueue test for ZeroGravity.

.DESCRIPTION
  Turn 1: Creates package.json, tsconfig.json, src/types.ts, and src/priorityQueue.ts
  Turn 2: Follow-up in the same chat session updating src/priorityQueue.ts and
          creating src/cli.ts and src/queue.test.ts.

.EXAMPLE
  .\tests\test-runs\ps\test_multi_turn_typescript.ps1 -RouterUrl "http://localhost:8000"
#>
param(
    [string]$RouterUrl = "http://localhost:8000",
    [string]$WorkspaceDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $WorkspaceDir) {
    if (Test-Path "$PSScriptRoot\..\..\..\workspace") {
        $WorkspaceDir = (Resolve-Path "$PSScriptRoot\..\..\..\workspace").Path
    } else {
        $WorkspaceDir = "$PSScriptRoot\workspace"
    }
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " ZeroGravity Multi-Turn Test: TypeScript PriorityQueue" -ForegroundColor Cyan
Write-Host " Target Router: $RouterUrl" -ForegroundColor Cyan
Write-Host " Target Workspace: $WorkspaceDir" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

try {
    $health = Invoke-RestMethod -Uri "$RouterUrl/healthz" -Method Get -TimeoutSec 5
    Write-Host "[1/4] Router reachable. Status: $($health.status), SignedIn: $($health.browser_signed_in)" -ForegroundColor Green
} catch {
    Write-Error "Cannot reach router at $RouterUrl. Ensure the stack is running."
    exit 1
}

Write-Host "`n----------------------------------------------------------" -ForegroundColor Yellow
Write-Host ">>> TURN 1: Requesting TypeScript PriorityQueue core files" -ForegroundColor Yellow
Write-Host "----------------------------------------------------------" -ForegroundColor Yellow

$turn1Prompt = @'
Build a modular TypeScript Priority Task Queue project. You MUST generate the following 4 files:
1. File: package.json
   - Name `ts-priority-queue`, scripts: `"build": "tsc"`, `"start": "tsc && node dist/cli.js"`, `"test": "tsc && node dist/queue.test.js"`.
   - Include `"typescript": "^5.6.0"` and `"@types/node": "^20.0.0"` in `devDependencies`.
2. File: tsconfig.json
   - Target `ES2022`, module `commonjs`, `rootDir`: `./src`, `outDir`: `./dist`, `strict`: true, `esModuleInterop`: true.
3. File: src/types.ts
   - Export type `Priority = "low" | "medium" | "high"`.
   - Export interface `TaskItem { id: string; title: string; priority: Priority; createdAt: number; }`.
4. File: src/priorityQueue.ts
   - Import `TaskItem` and `Priority` from `./types`.
   - Export class `PriorityQueue` with methods:
     - `enqueue(task: Omit<TaskItem, "createdAt">): TaskItem`
     - `dequeue(): TaskItem | undefined` (returns highest priority task first: high > medium > low, and FIFO within the same priority)
     - `size(): number`
     - `peek(): TaskItem | undefined`

Precede every file with a clear "File: <path>" header immediately preceding its code block.
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

$turn1TsFiles = Get-ChildItem -Path $WorkspaceDir -Recurse -Filter "*.ts" -ErrorAction SilentlyContinue
Write-Host "Workspace TS files after Turn 1 ($($turn1TsFiles.Count) found):" -ForegroundColor Cyan
$turn1TsFiles | ForEach-Object { Write-Host "  - $($_.FullName)" -ForegroundColor White }

Write-Host "`n----------------------------------------------------------" -ForegroundColor Yellow
Write-Host ">>> TURN 2: Requesting filterByPriority, CLI & unit tests" -ForegroundColor Yellow
Write-Host "----------------------------------------------------------" -ForegroundColor Yellow

$turn2Prompt = @'
Great! Now expand our TypeScript PriorityQueue project by adding a CLI demo and a self-contained test suite. Generate the following 3 files:
1. File: src/priorityQueue.ts
   - Keep existing functionality and add a new method `filterByPriority(priority: Priority): TaskItem[]` and validation in `enqueue` that throws an `Error("Task title cannot be empty")` if `title.trim()` is empty.
2. File: src/cli.ts
   - Import `PriorityQueue` from `./priorityQueue`.
   - Enqueue 3 sample tasks (`low`, `high`, `medium`), print the queue size, and dequeue all items printing their order.
3. File: src/queue.test.ts
   - Use Node's built-in `import assert from "node:assert/strict"`.
   - Test that `dequeue()` returns `"high"` before `"medium"` and `"low"`.
   - Test `filterByPriority("high")`.
   - Test that `enqueue` with an empty title throws an Error.
   - Print `"ALL TESTS PASSED"` at the end.

Precede every file with a clear "File: <path>" header immediately preceding its code block.
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

$allTsFiles = Get-ChildItem -Path $WorkspaceDir -Recurse -Filter "*.ts" -ErrorAction SilentlyContinue
Write-Host "`nTotal workspace TS files after Turn 2 ($($allTsFiles.Count) found):" -ForegroundColor Cyan
$allTsFiles | ForEach-Object { Write-Host "  - $($_.FullName)" -ForegroundColor White }

if ($allTsFiles.Count -ge 4) {
    Write-Host "`n[PASS] MULTI-TURN TYPESCRIPT TEST PASSED: Generated $($allTsFiles.Count) TypeScript files across 2 turns." -ForegroundColor Green
} else {
    Write-Warning "`n[WARN] Expected at least 4 TS files total, found: $($allTsFiles.Count)"
    exit 1
}

