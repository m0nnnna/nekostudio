# NekoStudio setup for Windows 10/11. Safe to re-run. Usage: .\setup.ps1 [-NoTrain]
param([switch]$NoTrain)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
. (Join-Path $PSScriptRoot 'nekoenv.ps1')
$TorchIndex = 'https://download.pytorch.org/whl/cu128'

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Need($cmd, $winget) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "'$cmd' not found. Install it with:  winget install $winget   (then open a new terminal and re-run)"
    }
}
function Run { & $args[0] $args[1..($args.Count - 1)]; if ($LASTEXITCODE -ne 0) { throw "Command failed: $($args -join ' ')" } }

Step 'Checking NVIDIA driver'
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
} else {
    Write-Warning 'nvidia-smi not found. Install the NVIDIA driver; the UI works without it but generation does not.'
}

Step 'Checking git and ffmpeg'
Need git 'Git.Git'
Need ffmpeg 'Gyan.FFmpeg'

Step 'Checking uv'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
Need uv 'astral-sh.uv'

if ($EnvDir -ne $Root) { Step "Install is on a network share: Python envs go to $EnvDir (data and models stay here)" }
Step 'Main environment (.venv, Python 3.12)'
$Py = Join-Path $EnvDir '.venv\Scripts\python.exe'
$TrainPy = Join-Path $EnvDir '.venv-train\Scripts\python.exe'
$Kohya = Join-Path $EnvDir 'vendor\sd-scripts'
if (-not (Test-Path $Py)) { Run uv venv --python 3.12 (Join-Path $EnvDir '.venv') }
Run uv pip install --python $Py torch torchvision --index-url $TorchIndex
Run uv pip install --python $Py -r requirements.txt

if (-not $NoTrain) {
    Step 'LoRA trainer (kohya sd-scripts, .venv-train, Python 3.10)'
    New-Item -ItemType Directory -Force (Join-Path $EnvDir 'vendor') | Out-Null
    if (Test-Path (Join-Path $Kohya '.git')) {
        Run git -C $Kohya fetch --depth 1 origin main
        Run git -C $Kohya reset --hard origin/main
    } else {
        Run git clone --depth 1 --branch main https://github.com/kohya-ss/sd-scripts $Kohya
    }
    if (-not (Test-Path $TrainPy)) { Run uv venv --python 3.10 (Join-Path $EnvDir '.venv-train') }
    Run uv pip install --python $TrainPy torch torchvision --index-url $TorchIndex
    Run uv pip install --python $TrainPy -r (Join-Path $Kohya 'requirements.txt') -r requirements-train.txt
} else { Write-Host 'Skipping trainer (-NoTrain).' }

Step 'Creating data folders'
foreach ($d in 'checkpoints', 'loras', 'vae') { New-Item -ItemType Directory -Force "data\models\$d" | Out-Null }

Step 'Start Menu shortcut'
$lnk = Join-Path ([Environment]::GetFolderPath('Programs')) 'NekoStudio.lnk'
$sh = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
# Straight to PowerShell, not run.bat: cmd.exe can't start in a \\server\share folder.
$sh.TargetPath = Join-Path $PSHOME 'powershell.exe'
$sh.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'run.ps1')`""
$sh.WorkingDirectory = $PSScriptRoot
$sh.IconLocation = (Join-Path $PSHOME 'powershell.exe') + ',0'
$sh.Save()

Write-Host "`nDone. Put checkpoints in $PSScriptRoot\data\models\checkpoints and start with run.bat" -ForegroundColor Green
