param([string]$Project = "examples/plant")
$ErrorActionPreference = "Stop"
Push-Location -LiteralPath $PSScriptRoot
try {
    $pythonPath = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw "Crea el entorno siguiendo README.md antes de ejecutar run.ps1."
    }
    & $pythonPath -m abscada $Project
} finally {
    Pop-Location
}
