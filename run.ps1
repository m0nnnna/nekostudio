# Start NekoStudio. Extra args go to the server (e.g. --port 7861).
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
. (Join-Path $PSScriptRoot 'nekoenv.ps1')
$py = Join-Path $EnvDir '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { Write-Error 'No Python env yet. Run setup.bat first.'; exit 1 }
& $py -m nekostudio --open @args
