<#
.SYNOPSIS
    Start the AI Stocks & News Analysis app (FastAPI backend + React frontend).

.DESCRIPTION
    On first run, creates the backend virtual environment and installs backend +
    frontend dependencies. Then launches both dev servers, each in its own
    PowerShell window:
      - Backend  -> http://localhost:8000  (API docs at /docs)
      - Frontend -> http://localhost:5173

.PARAMETER Setup
    Force the install/setup step even if .venv / node_modules already exist.

.EXAMPLE
    .\start.ps1
.EXAMPLE
    .\start.ps1 -Setup
#>
param(
    [switch]$Setup
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"

function Require-Command($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "'$name' was not found on PATH. $hint"
    }
}

Require-Command "python" "Install Python 3.11+ from https://www.python.org/downloads/"
Require-Command "npm" "Install Node.js 20.x from https://nodejs.org/"

# --- Backend setup (first run, or -Setup) ---
if ($Setup -or -not (Test-Path $venvPython)) {
    Write-Host "[setup] Creating backend virtual environment..." -ForegroundColor Cyan
    Push-Location $backend
    try {
        python -m venv .venv
        & $venvPython -m pip install --upgrade pip
        & $venvPython -m pip install -e ".[dev]"
    } finally {
        Pop-Location
    }
}

# --- Frontend setup (first run, or -Setup) ---
if ($Setup -or -not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "[setup] Installing frontend dependencies..." -ForegroundColor Cyan
    Push-Location $frontend
    try {
        npm install
    } finally {
        Pop-Location
    }
}

# --- Launch backend in its own window ---
Write-Host "[start] Backend  -> http://localhost:8000" -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$backend'; & '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --reload --port 8000"
)

# --- Launch frontend in its own window ---
Write-Host "[start] Frontend -> http://localhost:5173" -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$frontend'; npm run dev"
)

Write-Host ""
Write-Host "Two windows opened (one per server)." -ForegroundColor Yellow
Write-Host "  Frontend: http://localhost:5173" -ForegroundColor Yellow
Write-Host "  Backend:  http://localhost:8000  (docs at /docs)" -ForegroundColor Yellow
Write-Host "Close those windows (or Ctrl+C in each) to stop the servers."
