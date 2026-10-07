# Publica una version nueva de abSCADA (ver tools/release.py):
#   .\publicar-version.ps1 --beta              0.5.0b1 -> 0.5.0b2
#   .\publicar-version.ps1 --patch             beta -> version estable
#   .\publicar-version.ps1 --minor --dry-run   solo comprobar
# Solo ASCII en este archivo: Windows PowerShell 5.1 lee los .ps1 sin BOM como ANSI.
$ErrorActionPreference = "Stop"
Push-Location -LiteralPath $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
    if (-not (Test-Path -LiteralPath $python)) { throw "Crea el entorno siguiendo README.md antes de publicar." }
    $git = "C:\Program Files\Git\cmd"
    if ((Test-Path $git) -and -not (Get-Command git -ErrorAction SilentlyContinue)) { $env:PATH = "$git;" + $env:PATH }
    $gh = "C:\Program Files\GitHub CLI"
    if ((Test-Path $gh) -and -not (Get-Command gh -ErrorAction SilentlyContinue)) { $env:PATH = "$gh;" + $env:PATH }
    & $python tools/release.py @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
