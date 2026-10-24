# Dot-sourced by setup.ps1 and run.ps1. Sets $EnvDir: where .venv, .venv-train and vendor\ live.
# That is the install folder itself, unless it is on a network share (\\server\share or a mapped
# drive): Python can't load DLLs from a share quickly (or at all, under some policies) and each PC
# needs its own envs, so they go to %LOCALAPPDATA%\NekoStudio instead. Data and models stay on the share.
$Root = $PSScriptRoot
$net = $Root.StartsWith('\\')
if (-not $net) { try { $net = ([IO.DriveInfo]([IO.Path]::GetPathRoot($Root))).DriveType -eq 'Network' } catch {} }
$EnvDir = $Root
if ($net) {
    $sha = [Security.Cryptography.SHA1]::Create()
    $id = -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Root.ToLowerInvariant()))[0..3] | ForEach-Object { $_.ToString('x2') })
    $EnvDir = Join-Path $env:LOCALAPPDATA "NekoStudio\env-$id"
    New-Item -ItemType Directory -Force $EnvDir | Out-Null
    Set-Content -Path (Join-Path $EnvDir 'install-path.txt') -Value $Root
    $env:PYTHONPYCACHEPREFIX = Join-Path $EnvDir 'pycache'
}
$env:NEKOSTUDIO_ENV = $EnvDir
# uv's download cache defaults to C:\Users\<you>\AppData\Local\uv\cache; torch alone needs several GB there.
# Keep it next to the envs instead (same drive, so uv can hardlink from it), unless you set your own.
if (-not $env:UV_CACHE_DIR) { $env:UV_CACHE_DIR = Join-Path $EnvDir '.uv-cache' }
