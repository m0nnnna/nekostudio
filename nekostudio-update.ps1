# Update NekoStudio: newest release, or --edge for the newest commit of main. See --help.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
. (Join-Path $PSScriptRoot 'nekoenv.ps1')
$py = Join-Path $EnvDir '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
& $py -I (Join-Path $PSScriptRoot 'nekostudio\updater.py') @args
exit $LASTEXITCODE
