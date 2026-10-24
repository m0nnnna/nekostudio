#!/usr/bin/env bash
# NekoStudio setup for Ubuntu 22.04+. Safe to re-run (it updates).
# Usage: ./setup.sh [--no-train]
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
. ./nekoenv.sh
TRAIN=1
for a in "$@"; do
  case "$a" in
    --no-train) TRAIN=0 ;;
    -h|--help) echo "Usage: ./setup.sh [--no-train]"; exit 0 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done
log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

TORCH_INDEX="https://download.pytorch.org/whl/cu128"

log "Checking NVIDIA driver"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
else
  warn "nvidia-smi not found or failing. Install the NVIDIA driver (e.g. 'sudo ubuntu-drivers install'). Continuing; the UI works but generation needs a GPU."
fi

log "Checking system packages (git, ffmpeg, curl)"
missing=()
for c in git ffmpeg curl; do command -v "$c" >/dev/null 2>&1 || missing+=("$c"); done
if [ "${#missing[@]}" -gt 0 ]; then
  cmd="apt-get install -y ${missing[*]}"
  if [ "$(id -u)" -eq 0 ]; then apt-get update && $cmd
  elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then sudo apt-get update && sudo $cmd
  elif command -v sudo >/dev/null 2>&1 && [ -t 0 ]; then sudo apt-get update && sudo $cmd
  else die "Missing: ${missing[*]}. Run:  sudo $cmd   then re-run ./setup.sh"; fi
fi

export PATH="$HOME/.local/bin:$PATH"
log "Checking uv"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || die "uv install failed; see https://docs.astral.sh/uv/"

[ "$ENV_DIR" = "$ROOT" ] || log "Install is on a network share: Python envs go to $ENV_DIR (data and models stay here)"
log "Main environment (.venv, Python 3.12)"
[ -x "$ENV_DIR/.venv/bin/python" ] || uv venv --python 3.12 "$ENV_DIR/.venv"
uv pip install --python "$ENV_DIR/.venv/bin/python" torch torchvision --index-url "$TORCH_INDEX"
uv pip install --python "$ENV_DIR/.venv/bin/python" -r requirements.txt

if [ "$TRAIN" -eq 1 ]; then
  log "LoRA trainer (kohya sd-scripts, separate .venv-train, Python 3.10)"
  mkdir -p "$ENV_DIR/vendor"
  if [ -d "$ENV_DIR/vendor/sd-scripts"/.git ]; then
    git -C "$ENV_DIR/vendor/sd-scripts" fetch --depth 1 origin main && git -C "$ENV_DIR/vendor/sd-scripts" reset --hard origin/main
  else
    git clone --depth 1 --branch main https://github.com/kohya-ss/sd-scripts "$ENV_DIR/vendor/sd-scripts"
  fi
  [ -x "$ENV_DIR/.venv-train/bin/python" ] || uv venv --python 3.10 "$ENV_DIR/.venv-train"
  uv pip install --python "$ENV_DIR/.venv-train/bin/python" torch torchvision --index-url "$TORCH_INDEX"
  uv pip install --python "$ENV_DIR/.venv-train/bin/python" -r "$ENV_DIR/vendor/sd-scripts"/requirements.txt -r requirements-train.txt
else
  echo "Skipping trainer (--no-train)."
fi

log "Creating data folders"
mkdir -p data/models/checkpoints data/models/loras data/models/vae

log "Desktop entry"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/nekostudio.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=NekoStudio
Comment=Local AI art studio
Exec=bash "$(printf %s "$ROOT" | sed 's/[\\"`$]/\\&/g')/run.sh" --open
Path=$ROOT
Terminal=true
Categories=Graphics;
DESK

log "Done. Put checkpoints in $ROOT/data/models/checkpoints and start with ./run.sh"
