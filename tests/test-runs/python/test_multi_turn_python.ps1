<#
.SYNOPSIS
  Multi-turn (2 turns) Python LRUCache test for ZeroGravity.

.DESCRIPTION
  Turn 1: Creates src/lru_cache.py and src/cli.py
  Turn 2: Follow-up in the same chat session adding stats() to src/lru_cache.py
          and creating tests/test_lru_cache.py.

.EXAMPLE
  .\tests\test-runs\python\test_multi_turn_python.ps1 -RouterUrl "http://localhost:8000"
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
Write-Host " ZeroGravity Multi-Turn Test: Python LRUCache" -ForegroundColor Cyan
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
Write-Host ">>> TURN 1: Requesting Python LRUCache & CLI demo" -ForegroundColor Yellow
Write-Host "----------------------------------------------------------" -ForegroundColor Yellow

$turn1Prompt = @'
Build a modular Python LRU Cache project using only the Python standard library. You MUST generate the following 2 files:
1. File: src/lru_cache.py
   - Implement class `LRUCache` using `collections.OrderedDict` with `capacity: int` (raise `ValueError("Capacity must be >= 1")` if `capacity < 1`).
   - Methods:
     - `get(key: str, default=None)`: returns the value if present and marks the key as most recently used, otherwise returns `default`.
     - `put(key: str, value) -> None`: inserts or updates the key as most recently used, evicting the least recently used item if over `capacity`.
     - `delete(key: str) -> bool`: removes the key and returns `True` if it existed, else `False`.
     - `size() -> int` and `keys() -> list[str]` (ordered from least to most recently used).
2. File: src/cli.py
   - Import `LRUCache` from `lru_cache` (or `src.lru_cache`).
   - Create an `LRUCache(capacity=3)`, insert `"a": 1`, `"b": 2`, `"c": 3`, access `"a"`, insert `"d": 4` (which should evict `"b"`), and print the remaining keys and values.

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

$turn1PyFiles = Get-ChildItem -Path $WorkspaceDir -Recurse -Filter "*.py" -ErrorAction SilentlyContinue
Write-Host "Workspace Python files after Turn 1 ($($turn1PyFiles.Count) found):" -ForegroundColor Cyan
$turn1PyFiles | ForEach-Object { Write-Host "  - $($_.FullName)" -ForegroundColor White }

Write-Host "`n----------------------------------------------------------" -ForegroundColor Yellow
Write-Host ">>> TURN 2: Requesting stats() & unittest suite" -ForegroundColor Yellow
Write-Host "----------------------------------------------------------" -ForegroundColor Yellow

$turn2Prompt = @'
Great! Now expand our Python LRU Cache project by adding statistics tracking and a `unittest` test suite. Generate the following 2 files:
1. File: src/lru_cache.py
   - Keep all existing functionality on `LRUCache` and add hit/miss tracking (`hits` and `misses` counters incremented in `get()`) plus a method `stats() -> dict` returning `{"hits": self.hits, "misses": self.misses, "size": self.size(), "capacity": self.capacity}`.
2. File: tests/test_lru_cache.py
   - Use Python's built-in `unittest` module (`unittest.TestCase`).
   - Add tests verifying:
     - LRU eviction order when capacity is exceeded and after `get()` refreshes a key.
     - `ValueError` is raised when `capacity < 1`.
     - `stats()` accurately counts cache `hits` and `misses`.
     - `delete()` removes keys properly.

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

$allPyFiles = Get-ChildItem -Path $WorkspaceDir -Recurse -Filter "*.py" -ErrorAction SilentlyContinue
Write-Host "`nTotal workspace Python files after Turn 2 ($($allPyFiles.Count) found):" -ForegroundColor Cyan
$allPyFiles | ForEach-Object { Write-Host "  - $($_.FullName)" -ForegroundColor White }

if ($allPyFiles.Count -ge 3) {
    Write-Host "`n[PASS] MULTI-TURN PYTHON TEST PASSED: Generated $($allPyFiles.Count) Python files across 2 turns." -ForegroundColor Green
} else {
    Write-Warning "`n[WARN] Expected at least 3 Python files total, found: $($allPyFiles.Count)"
    exit 1
}

