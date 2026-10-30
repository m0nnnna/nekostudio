"""Paths and persistent settings. Importing this module creates the data directory tree."""
from __future__ import annotations

import copy
import json
import os
import threading
from urllib.parse import quote
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Python envs + the kohya checkout. run/setup scripts point this at local disk when ROOT is on a network
# share (venvs on SMB are slow and each PC needs its own); otherwise it is ROOT.
ENV_DIR = Path(os.environ.get("NEKOSTUDIO_ENV") or ROOT).resolve()
HOME = Path(os.environ.get("NEKOSTUDIO_HOME") or ROOT / "data").resolve()

SETTINGS_FILE = HOME / "settings.json"


def _models_root() -> Path:
    """Models + HF cache can live on another drive: env NEKOSTUDIO_MODELS or "models_dir" in settings.json."""
    d = os.environ.get("NEKOSTUDIO_MODELS")
    if not d:
        try:
            d = json.loads(SETTINGS_FILE.read_text("utf-8")).get("models_dir")
        except (OSError, ValueError):
            d = None
    if d:
        p = Path(d).expanduser()
        # A shared install can be started from Linux and Windows; a models_dir from the other OS
        # (or an unplugged drive) must not turn into a stray folder here.
        if p.is_absolute() and p.is_dir():
            return p.resolve()
        print(f"[nekostudio] models_dir {d!r} not found on this PC, using {HOME / 'models'}", flush=True)
    return HOME / "models"


MODELS = _models_root()
CHECKPOINTS = MODELS / "checkpoints"
LORAS = MODELS / "loras"
VAES = MODELS / "vae"
TAGS = MODELS / "tags"
LLMS = MODELS / "llm"
# Multi-file models (video, IP-Adapter) as plain folders, one per HF repo: repos/<owner>--<name>/
REPOS = MODELS / "repos"
OUTPUTS = HOME / "outputs"
IMAGES = OUTPUTS / "images"
VIDEOS = OUTPUTS / "videos"
DATASETS = HOME / "datasets"
TRAINING = HOME / "training"
HF_HOME = MODELS / "hf" if MODELS != HOME / "models" else HOME / "hf"
WEB_DIR = ROOT / "web"
VENDOR = ENV_DIR / "vendor"

HOME.mkdir(parents=True, exist_ok=True)
for _d in (CHECKPOINTS, LORAS, VAES, TAGS, LLMS, REPOS, IMAGES, VIDEOS, DATASETS, TRAINING, HF_HOME):
    _d.mkdir(parents=True, exist_ok=True)

# Model downloads (diffusers, WD14 tagger...) stay inside the data dir unless the user set their own.
os.environ.setdefault("HF_HOME", str(HF_HOME))
# Plain single-stream HTTP for HF downloads (xet fetches many chunks in parallel and keeps a chunk cache).
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
# Less VRAM fragmentation: video decoding on 12 GB cards runs out of memory without it.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
# Shares often can't do symlinks; huggingface_hub then copies into the cache by itself, no need to warn.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

DEFAULT_NEGATIVE = (
    "score_6, score_5, score_4, worst quality, low quality, bad anatomy, bad hands, "
    "missing fingers, extra digits, watermark, text, signature, jpeg artifacts, blurry"
)

DEFAULTS: dict = {
    "skin": "mine",
    "accent": "#ff3d7f",
    "motion": True,
    "vram_mode": "auto",  # auto | low | high
    "default_negative": DEFAULT_NEGATIVE,
    "civitai_token": "",
    "llm_gpu_layers": 0,   # local translator: 0 = CPU only (never fights SDXL for VRAM), -1 = all layers on GPU
    "llm": {"base_url": "http://127.0.0.1:11434/v1", "model": "", "api_key": ""},
    "video_models": [
        {"id": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers", "label": "Wan 2.1 T2V 1.3B (480p, fits 12 GB)"},
        {"id": "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers", "label": "Wan 2.1 I2V 14B 480p (optional, heavy)"},
    ],
}

MASK = "••••"
_lock = threading.Lock()


def _merge(base: dict, new: dict) -> dict:
    for k, v in new.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load_settings() -> dict:
    data = copy.deepcopy(DEFAULTS)
    with _lock:
        try:
            _merge(data, json.loads(SETTINGS_FILE.read_text("utf-8")))
        except (OSError, ValueError):
            pass
    return data


def save_settings(update: dict) -> dict:
    """Merge `update` into the stored settings. A masked api_key keeps the stored one."""
    update = copy.deepcopy(update or {})
    # Tolerate flat llm_* / base_url / model / api_key keys from the UI.
    llm = update.setdefault("llm", {}) if isinstance(update.get("llm", {}), dict) else {}
    for flat, key in (("llm_base_url", "base_url"), ("llm_model", "model"), ("llm_api_key", "api_key"),
                      ("base_url", "base_url"), ("model", "model"), ("api_key", "api_key")):
        if flat in update:
            llm[key] = update.pop(flat)
    update["llm"] = llm
    update.pop("paths", None)
    if llm.get("api_key") == MASK:
        llm.pop("api_key")
    if update.get("civitai_token") == MASK:
        update.pop("civitai_token")
    current = load_settings()
    _merge(current, update)
    with _lock:
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, indent=2), "utf-8")
        tmp.replace(SETTINGS_FILE)
    return current


def public_settings() -> dict:
    """Settings as sent to the browser: api_key masked, read-only paths added."""
    s = load_settings()
    if s["llm"].get("api_key"):
        s["llm"]["api_key"] = MASK
    if s.get("civitai_token"):
        s["civitai_token"] = MASK
    s["paths"] = {k: str(v) for k, v in {
        "home": HOME, "checkpoints": CHECKPOINTS, "loras": LORAS, "vae": VAES,
        "outputs": OUTPUTS, "datasets": DATASETS, "training": TRAINING}.items()}
    return s


def file_url(path: Path) -> str:
    """Map a file under outputs/ or datasets/ to its /files URL."""
    path = Path(path).resolve()
    for base, prefix in ((OUTPUTS, "/files/outputs/"), (DATASETS, "/files/datasets/")):
        try:
            return prefix + quote(path.relative_to(base).as_posix())
        except ValueError:
            continue
    raise ValueError(f"{path} is not served")


def train_python() -> Path:
    sub = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return ENV_DIR / ".venv-train" / sub


def train_ready() -> bool:
    return train_python().exists() and (VENDOR / "sd-scripts" / "train_network.py").exists()


_NET_FS = {"cifs", "smb3", "smbfs", "nfs", "nfs4", "9p", "fuse.gvfsd-fuse", "fuse.sshfs", "afpfs"}


def on_network(path: Path) -> bool:
    """True when `path` lives on a network share (UNC path, mapped drive, or a CIFS/NFS/gvfs mount)."""
    path = Path(path)
    if os.name == "nt":
        s = str(path)
        if s.startswith("\\\\"):
            return True
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(path.drive + "\\") == 4  # DRIVE_REMOTE
    try:
        best, fstype = "", ""
        target = str(path.resolve())
        with open("/proc/self/mounts", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                mnt = parts[1].replace("\\040", " ")
                if (target == mnt or target.startswith(mnt.rstrip("/") + "/")) and len(mnt) >= len(best):
                    best, fstype = mnt, parts[2]
        return fstype in _NET_FS
    except OSError:
        return False
