param([ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $projectPython)) {
        python -m venv (Join-Path $PSScriptRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
    }
    & $projectPython -m pip install -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    Push-Location -LiteralPath (Join-Path $PSScriptRoot 'frontend')
    try {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'Node.js 22.12+ or 24+ is required.' }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
    Write-Host "applyproof: http://127.0.0.1:$Port"
    & $projectPython -m uvicorn applyproof.api:app --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'Server failed. Check whether the port is already in use.' }
} finally { Pop-Location }
