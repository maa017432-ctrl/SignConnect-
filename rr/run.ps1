# SignConnect launcher — always uses the .venv311 Python 3.11 interpreter.
# Usage: .\run.ps1
# Do NOT use plain "python app.py" — that picks up the wrong global Python.

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$PythonExe   = Join-Path $ProjectRoot ".venv311\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Error @"
.venv311 not found at: $PythonExe

Set it up once with:
    python3.11 -m venv .venv311
    .\.venv311\Scripts\pip install -r requirements.txt
"@
    exit 1
}

$ModelPath = Join-Path $ProjectRoot "models\gesture_model.h5"
if (-not (Test-Path $ModelPath)) {
    Write-Host "Model not found — generating demo model..." -ForegroundColor Yellow
    & $PythonExe (Join-Path $ProjectRoot "scripts\generate_demo_model.py")
}

Write-Host "Starting SignConnect using $PythonExe ..." -ForegroundColor Cyan
& $PythonExe (Join-Path $ProjectRoot "app.py")
