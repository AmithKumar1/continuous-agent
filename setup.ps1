# ==============================================================================
# Continuous Agent Automated Setup Script (Windows PowerShell)
# ==============================================================================

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "    Continuous Agent Environment Bootstrap & Toolchain   " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
Write-Host "[INFO] Checking Python environment..." -ForegroundColor DarkCyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Python is not found on PATH. Please install Python 3.10+ from python.org." -ForegroundColor Red
    exit 1
}

$pyVersion = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "[SUCCESS] Python version verified: $pyVersion" -ForegroundColor Green

# 2. Virtual Environment
if (-not (Test-Path ".venv")) {
    Write-Host "[INFO] Creating Python virtual environment in .venv/..." -ForegroundColor DarkCyan
    python -m venv .venv
}

Write-Host "[INFO] Activating virtual environment..." -ForegroundColor DarkCyan
$venvPython = ".venv\Scripts\python.exe"
$venvPip = ".venv\Scripts\pip.exe"

# 3. Upgrade Pip & Install Requirements
Write-Host "[INFO] Upgrading pip, setuptools, and wheel..." -ForegroundColor DarkCyan
& $venvPip install --upgrade pip wheel setuptools --quiet

if (Test-Path "requirements.txt") {
    Write-Host "[INFO] Installing Python dependencies (FastAPI, Z3, Wasmtime, Chromadb)..." -ForegroundColor DarkCyan
    & $venvPip install -r requirements.txt --quiet
    Write-Host "[SUCCESS] Python packages installed successfully." -ForegroundColor Green
} else {
    Write-Host "[ERROR] requirements.txt not found." -ForegroundColor Red
    exit 1
}

# 4. Environment Template Initialization
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Host "[INFO] Initializing .env from .env.example..." -ForegroundColor DarkCyan
        Copy-Item ".env.example" ".env"
        Write-Host "[WARN] Created .env template. Update it with your API keys and tokens." -ForegroundColor Yellow
    }
} else {
    Write-Host "[SUCCESS] Existing .env file detected." -ForegroundColor Green
}

# 5. Pre-flight diagnostics
Write-Host ""
Write-Host "[INFO] Running pre-flight diagnostic sanity checks..." -ForegroundColor DarkCyan
if (Test-Path "preflight.py") {
    & $venvPython preflight.py
}

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "             SETUP COMPLETED SUCCESSFULLY!                " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To activate your environment and launch the agent:" -ForegroundColor White
Write-Host "  .venv\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host "  python main.py" -ForegroundColor Cyan
Write-Host ""
