<#
.SYNOPSIS
  Multi-turn (2 turns) test for ZeroGravity:
  Java Spring Boot & Gradle Task Management Service.
  Tests multi-file generation and automatic package-to-directory path resolution.

.DESCRIPTION
  Turn 1: Creates build.gradle, application.yaml, Task (Model), TaskDto (DTO),
          TaskService, TaskController, and TaskManagerApplication.
  Turn 2: Follow-up in the same chat session creating TaskNotFoundException,
          GlobalExceptionHandler, and TaskControllerTest.

.EXAMPLE
  .\test_multi_turn_springboot.ps1 -RouterUrl "http://localhost:8000"
#>
param(
    [string]$RouterUrl = "http://localhost:8000",
    [string]$WorkspaceDir = "",
    [switch]$SkipClean
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
Write-Host " ZeroGravity Multi-Turn Test: Java Spring Boot & Gradle" -ForegroundColor Cyan
Write-Host " Target Router: $RouterUrl" -ForegroundColor Cyan
Write-Host " Target Workspace: $WorkspaceDir" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 0. Clean previous workspace if requested
if (-not $SkipClean) {
    Write-Host "`n[0/4] Cleaning workspace before test run..." -ForegroundColor Gray
    if (Test-Path "$WorkspaceDir\src") {
        Remove-Item -Recurse -Force "$WorkspaceDir\src"
    }
    Get-ChildItem -Path $WorkspaceDir -File | Where-Object { $_.Name -ne ".gitkeep" } | Remove-Item -Force
    Write-Host "Workspace cleaned." -ForegroundColor Gray
}

# 1. Check Router Health
try {
    $health = Invoke-RestMethod -Uri "$RouterUrl/healthz" -Method Get -TimeoutSec 5
    Write-Host "`n[1/4] Router is reachable. Status: $($health.status), Local AI: $($health.local_ai_enabled)" -ForegroundColor Green
} catch {
    Write-Error "Cannot reach router at $RouterUrl. Ensure the stack or local router is running."
    exit 1
}

# -------------------------------------------------------------
# Turn 1: Initial Prompt - Spring Boot 3 Gradle Architecture
# -------------------------------------------------------------
Write-Host "`n----------------------------------------------------------" -ForegroundColor Yellow
Write-Host ">>> TURN 1: Requesting Spring Boot 3 Task Management Service" -ForegroundColor Yellow
Write-Host "----------------------------------------------------------" -ForegroundColor Yellow

$turn1Prompt = @'
Build a Spring Boot 3 Gradle REST API for a Task Management application under base package `com.example.taskmanager`.
You MUST generate the following files:
1. File: build.gradle
   - Configure Gradle with Java 17 and Spring Boot 3 plugin.
   - Include dependencies for `spring-boot-starter-web` and `spring-boot-starter-test`.
2. File: src/main/resources/application.yaml
   - Configure server port 8080 and application name `task-manager`.
3. File: Task.java
   - Entity/Model class with `package com.example.taskmanager.model;`.
   - Fields: id (Long), title (String), description (String), completed (boolean). Include constructors, getters, and setters.
4. File: TaskDto.java
   - DTO record or class with `package com.example.taskmanager.dto;`. Fields: title, description, completed.
5. File: TaskService.java
   - Service with `package com.example.taskmanager.service;`.
   - In-memory store using ConcurrentHashMap, methods: getAllTasks(), getTaskById(Long id), createTask(TaskDto dto).
6. File: TaskController.java
   - REST Controller with `package com.example.taskmanager.controller;`.
   - Endpoints: GET /api/tasks, GET /api/tasks/{id}, POST /api/tasks.
7. File: TaskManagerApplication.java
   - Main Spring Boot application class with `package com.example.taskmanager;` annotated with @SpringBootApplication.

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
Write-Host "Assistant Reply Summary:" -ForegroundColor Gray
Write-Host ($turn1Reply.Substring(0, [Math]::Min(350, $turn1Reply.Length)) + "...")

# Verify Turn 1 Java and Gradle files in workspace
$turn1Files = Get-ChildItem -Path $WorkspaceDir -Recurse -File | Where-Object { $_.FullName -notmatch "\\\.gemini-history\\" }
Write-Host "`nWorkspace files after Turn 1 ($($turn1Files.Count) found):" -ForegroundColor Cyan
$turn1Files | ForEach-Object { Write-Host "  - $($_.FullName)" -ForegroundColor White }

# Check that package directory mapping worked for Java files
$javaMainFiles = Get-ChildItem -Path "$WorkspaceDir\src\main\java" -Recurse -Filter "*.java" -ErrorAction SilentlyContinue
Write-Host "Resolved src/main/java files ($($javaMainFiles.Count) found):" -ForegroundColor Cyan
$javaMainFiles | ForEach-Object { Write-Host "    [OK] $($_.FullName.Replace($WorkspaceDir, ''))" -ForegroundColor Green }

if ($turn1Files.Count -lt 5) {
    Write-Warning "Turn 1 produced fewer files than expected ($($turn1Files.Count))."
} else {
    Write-Host "SUCCESS: Turn 1 produced $($turn1Files.Count) files." -ForegroundColor Green
}

# -------------------------------------------------------------
# Turn 2: Follow-up Prompt in the same conversation
# -------------------------------------------------------------
Write-Host "`n----------------------------------------------------------" -ForegroundColor Yellow
Write-Host ">>> TURN 2: Adding Exception Handling & Unit / Controller Tests" -ForegroundColor Yellow
Write-Host "----------------------------------------------------------" -ForegroundColor Yellow

$turn2Prompt = @'
Great! Now expand our Spring Boot Task Management application by adding error handling and automated unit tests:
1. File: TaskNotFoundException.java
   - Custom runtime exception with `package com.example.taskmanager.exception;` taking Long id.
2. File: GlobalExceptionHandler.java
   - Exception handler with `package com.example.taskmanager.controller;` annotated with @RestControllerAdvice.
   - Handles TaskNotFoundException and returns 404 NOT_FOUND with an ErrorResponse(int status, String message) record.
3. File: TaskControllerTest.java
   - Test class with `package com.example.taskmanager.controller;` using JUnit 5 `@Test` and `@WebMvcTest(TaskController.class)`.
   - Mock TaskService and verify GET /api/tasks returns 200 OK, and GET /api/tasks/999 returns 404 NOT_FOUND.

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

# Verify All files in workspace
$allFiles = Get-ChildItem -Path $WorkspaceDir -Recurse -File | Where-Object { $_.FullName -notmatch "\\\.gemini-history\\" }
Write-Host "`nTotal workspace files after Turn 2 ($($allFiles.Count) found):" -ForegroundColor Cyan
$allFiles | ForEach-Object { Write-Host "  - $($_.FullName)" -ForegroundColor White }

# Check test directory mapping
$testFiles = Get-ChildItem -Path "$WorkspaceDir\src\test\java" -Recurse -Filter "*.java" -ErrorAction SilentlyContinue
Write-Host "`nResolved src/test/java files ($($testFiles.Count) found):" -ForegroundColor Cyan
$testFiles | ForEach-Object { Write-Host "    [OK] $($_.FullName.Replace($WorkspaceDir, ''))" -ForegroundColor Green }

# Check .gemini-history
$historyDir = Join-Path $WorkspaceDir ".gemini-history"
if (Test-Path $historyDir) {
    Write-Host "`nAudit History Log (.gemini-history):" -ForegroundColor Cyan
    Get-ChildItem -Path "$historyDir\turns" -Directory | ForEach-Object {
        Write-Host "  Turn Log: $($_.Name)" -ForegroundColor Gray
    }
}

if ($allFiles.Count -ge 8 -and $testFiles.Count -ge 1) {
    Write-Host "`n🎉 SPRING BOOT MULTI-TURN TEST PASSED: Generated $($allFiles.Count) files across 2 turns with full package-to-directory path resolution." -ForegroundColor Green
} else {
    Write-Warning "`n⚠️ Expected at least 8 files total and at least 1 test file. Found: $($allFiles.Count) total, $($testFiles.Count) test files."
}

