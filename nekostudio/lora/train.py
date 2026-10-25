"""Builds a kohya sd-scripts run and launches it inside the separate training venv."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from .. import config
from ..engine import image as image_engine
from ..engine import video as video_engine
from ..jobs import Job
from ..prompts import local_llm
from . import dataset as ds

PRESETS = {
    "character": dict(dim=16, alpha=16, lr=2e-4, repeats=10, epochs=10),
    "style": dict(dim=32, alpha=16, lr=1.5e-4, repeats=5, epochs=12),
    "concept": dict(dim=16, alpha=16, lr=2e-4, repeats=8, epochs=10),
}

# Tags that describe the shot, not the subject: never folded into the trigger word.
KEEP_TAGS = {
    "1girl", "1boy", "1other", "2girls", "2boys", "multiple girls", "multiple boys", "solo", "solo focus",
    "simple background", "white background", "grey background", "black background", "looking at viewer",
    "upper body", "full body", "cowboy shot", "portrait", "close-up", "standing", "sitting", "smile",
    "closed mouth", "open mouth", "outdoors", "indoors", "from side", "from behind", "from above", "from below",
}


def _core_tags(caps: list[list[str]], share: float = 0.5) -> set[str]:
    """Tags on at least `share` of the images: the subject's fixed look (hair, eyes, outfit...).
    Removing them from the captions makes the trigger word carry that look, which is what a
    character/outfit LoRA is for; left in, the model ties the look to those tags instead."""
    if len(caps) < 4:
        return set()
    counts: dict[str, int] = {}
    for tags in caps:
        for t in set(tags):
            counts[t] = counts.get(t, 0) + 1
    return {t for t, n in counts.items() if n >= share * len(caps) and t not in KEEP_TAGS}
SETUP_HINT = "Run ./setup.sh (Ubuntu) or setup.bat (Windows) without --no-train to install the trainer."


def _toml_path(p) -> str:
    return str(p).replace("\\", "/")


def _prepare_dataset(name: str, trigger: str, dest, prune_core: bool = False):
    """Copy images and captions into the training dir, trigger word forced to the front, and with
    `prune_core` the subject's always-present tags removed (see _core_tags).
    The original dataset stays untouched, so changing the trigger later is harmless."""
    src = ds._dir(name)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    imgs = ds._images(src)
    caps = []
    for img in imgs:
        cp = ds._caption_path(img)
        tags = [t.strip() for t in (cp.read_text("utf-8") if cp.exists() else "").split(",") if t.strip()]
        caps.append([t for t in tags if t.lower() != trigger.lower()])
    core = _core_tags(caps) if prune_core else set()
    count = 0
    for img, tags in zip(imgs, caps):
        try:
            os.link(img, dest / img.name)
        except OSError:
            shutil.copy2(img, dest / img.name)
        cap = ", ".join(t for t in tags if t not in core)
        if trigger and not cap.lower().startswith(trigger.lower()):
            cap = f"{trigger}, {cap}" if cap else trigger
        (dest / (img.stem + ".txt")).write_text(cap, "utf-8")
        count += 1
    if count == 0:
        raise RuntimeError("Dataset has no images.")
    return count, sorted(core)


# Native crashes: Windows access violation (0xC0000005, as unsigned or signed exit code), Linux SIGSEGV/SIGKILL.
CRASH_CODES = {3221225477, -1073741819, -11, 139, -9, 137}


def _ram_gb() -> tuple[float, float]:
    """(available RAM, available RAM + page file) in GB, or (-1, -1) if unknown."""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong)] + \
                    [(n, ctypes.c_ulonglong) for n in ("tot", "avail", "tot_pf", "avail_pf", "tot_v", "avail_v", "ext")]
            m = MS()
            m.len = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.avail / 2**30, m.avail_pf / 2**30
        info = dict(l.split(":", 1) for l in open("/proc/meminfo", encoding="utf-8"))
        kb = lambda k: int(info[k].split()[0]) / 2**20  # noqa: E731
        return kb("MemAvailable"), kb("MemAvailable") + kb("SwapFree")
    except Exception:  # noqa: BLE001
        return -1, -1


def run(job: Job, p: dict):
    if not config.train_ready():
        raise RuntimeError("LoRA trainer is not installed. " + SETUP_HINT)
    name = re.sub(r"[^A-Za-z0-9_-]", "_", p.get("name") or "")
    if not name:
        raise RuntimeError("Give the LoRA a name.")
    preset = dict(PRESETS.get(p.get("preset") or "character", PRESETS["character"]))
    preset.update({k: v for k, v in (p.get("overrides") or {}).items() if v not in (None, "")})
    trigger = (p.get("trigger") or ds._meta(ds._dir(p["dataset"])).get("trigger", "")).strip()

    ckpt_name = p.get("base_checkpoint") or ""
    ckpt = config.CHECKPOINTS / ckpt_name
    if not ckpt.is_file():
        raise RuntimeError("Pick a base checkpoint from data/models/checkpoints/.")
    kind = image_engine.detect_kind(ckpt)
    sdxl = kind != "sd15"
    res = int(preset.get("resolution") or (1024 if sdxl else 512))

    # Training needs the whole GPU, and loading SDXL in the trainer needs a lot of RAM: drop everything we hold.
    local_llm.unload()
    image_engine.unload()
    video_engine.unload()

    work = config.TRAINING / name
    out_dir, log_dir, sample_dir = work / "output", work / "logs", work / "sample"
    for d in (out_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)
    n_images, core = _prepare_dataset(p["dataset"], trigger, work / "dataset", bool(p.get("prune_core")))
    if core:
        job.update(message=f"'{trigger}' will learn: {', '.join(core[:12])}")

    (work / "dataset.toml").write_text(f"""[general]
shuffle_caption = true
keep_tokens = 1
caption_extension = ".txt"

[[datasets]]
resolution = {res}
batch_size = 1
enable_bucket = true
min_bucket_reso = {res // 2}
max_bucket_reso = {res * 3 // 2}
bucket_reso_steps = 64

  [[datasets.subsets]]
  image_dir = "{_toml_path(work / 'dataset')}"
  num_repeats = {int(preset['repeats'])}
""", "utf-8")
    sample_prompt = (trigger + ", " if trigger else "") + "1girl, solo, upper body" + \
        f" --w {res} --h {res} --s 24 --l 7 --d 42"
    (work / "sample_prompts.txt").write_text(sample_prompt + "\n", "utf-8")

    script = "sdxl_train_network.py" if sdxl else "train_network.py"
    args = [
        str(config.train_python()), str(config.VENDOR / "sd-scripts" / script),
        "--pretrained_model_name_or_path", str(ckpt),
        "--dataset_config", str(work / "dataset.toml"),
        "--output_dir", str(out_dir), "--output_name", name, "--save_model_as", "safetensors",
        "--logging_dir", str(log_dir),
        "--network_module", "networks.lora",
        "--network_dim", str(int(preset["dim"])), "--network_alpha", str(float(preset["alpha"])),
        "--learning_rate", str(float(preset["lr"])),
        "--optimizer_type", "AdamW8bit", "--lr_scheduler", "cosine",
        "--max_train_epochs", str(int(preset["epochs"])), "--save_every_n_epochs", "1",
        "--mixed_precision", "bf16", "--save_precision", "fp16",
        "--gradient_checkpointing", "--cache_latents", "--cache_latents_to_disk", "--sdpa",
        "--max_data_loader_n_workers", "2", "--persistent_data_loader_workers",
        # No per-epoch sample images: decoding one with the fp32 VAE on top of the training state OOMs a 12 GB card.
        "--seed", "42",
    ]
    if sdxl:
        args += ["--no_half_vae", "--network_train_unet_only"]
        if os.name == "nt" or config.on_network(ckpt):
            # Read the checkpoint in one go instead of memory-mapping it: on Windows the mmap'd load crashed
            # kohya with 0xC0000005 right after "text encoder 1", and over SMB/NFS mmap reads in tiny chunks.
            args.append("--disable_mmap_load_safetensors")
    # No --clip_skip: kohya ignores it for SDXL (and only trains the UNet here anyway).

    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
               PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")
    job.update(progress=0, message=f"starting trainer ({n_images} images, {preset['epochs']} epochs)...")
    (work / "command.txt").write_text(" ".join(args), "utf-8")
    ram, commit = _ram_gb()
    proc = subprocess.Popen(args, cwd=str(config.VENDOR / "sd-scripts"), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    job.proc = proc
    tail: list[str] = []
    state = {"epoch": "", "loss": "", "seen": set()}
    step_re = re.compile(r"(\d+)/(\d+)\s*\[")
    loss_re = re.compile(r"(?:avr_loss|loss)=([0-9.]+)")
    epoch_re = re.compile(r"epoch\s+(\d+)/(\d+)")

    def emit_samples():
        if sample_dir.exists():
            for f in sorted(sample_dir.glob("*.png")):
                if f.name not in state["seen"]:
                    state["seen"].add(f.name)
                    dst = config.OUTPUTS / "training" / name
                    dst.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dst / f.name)
                    job.add_result(config.file_url(dst / f.name), meta={"kind": "sample", "lora": name})

    logf = open(work / "train.log", "w", encoding="utf-8", buffering=1)
    buf = b""
    while True:
        chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
        if not chunk:
            break
        buf += chunk
        *lines, buf = re.split(rb"[\r\n]", buf)  # tqdm redraws with \r
        for raw in lines:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            logf.write(line + "\n")
            tail = (tail + [line])[-25:]
            m = epoch_re.search(line)
            if m:
                state["epoch"] = f"epoch {m.group(1)}/{m.group(2)}"
                emit_samples()
            m = loss_re.search(line)
            if m:
                state["loss"] = m.group(1)
            m = step_re.search(line)
            if m and "steps" in line.lower():
                cur, tot = int(m.group(1)), int(m.group(2))
                msg = f"{state['epoch']} loss: {state['loss']}".strip() if state["loss"] else (state["epoch"] or f"steps {cur}/{tot}")
                job.update(progress=cur / max(tot, 1), step=cur, total=tot, message=msg)
        if job.cancel_event.is_set():
            proc.terminate()
    code = proc.wait()
    logf.close()
    job.check()
    emit_samples()
    if code != 0:
        if any("OutOfMemoryError" in l for l in tail):
            raise RuntimeError("Out of GPU memory while training. Close games or other GPU apps and try again, "
                               "or lower the resolution under ADVANCED.")
        if code in CRASH_CODES:
            mem = f" When it started, this PC had {ram:.0f} GB RAM free ({commit:.0f} GB with the page file)." if ram >= 0 else ""
            raise RuntimeError(
                "The trainer crashed, which almost always means it ran out of system RAM "
                f"(SDXL training needs about 16 GB free, plus a page file).{mem} Close browsers and games and try "
                "again. On Windows, let Windows manage the page file size (System > About > Advanced system "
                f"settings > Performance > Advanced > Virtual memory). Log: {work / 'train.log'}")
        raise RuntimeError("Trainer exited with code %s: %s" % (code, " | ".join(tail[-4:])))
    result = out_dir / f"{name}.safetensors"
    if not result.exists():
        found = sorted(out_dir.glob("*.safetensors"), key=lambda f: f.stat().st_mtime)
        if not found:
            raise RuntimeError("Training finished but produced no .safetensors file.")
        result = found[-1]
    shutil.copy2(result, config.LORAS / f"{name}.safetensors")
    # sidecar read by the LoRA list, so USE can add the trigger word and pick the base model later
    (config.LORAS / f"{name}.json").write_text(json.dumps({"trigger": trigger, "base": ckpt_name}), "utf-8")
    job.add_result("", meta={"kind": "lora", "name": f"{name}.safetensors", "trigger": trigger})
    job.update(progress=1, message=f"done: {name}.safetensors")


class _Phase:
    """Maps one phase of a combined job onto a slice of the overall progress bar."""

    def __init__(self, job: Job, lo: float, hi: float, label: str):
        object.__setattr__(self, "_job", job)
        object.__setattr__(self, "_span", (lo, hi, label))

    def update(self, progress=None, step=None, total=None, message=None):
        lo, hi, label = self._span
        if step is not None and total and label == "tagging":
            message = f"tagging {step}/{total}"
        elif message is not None and label == "training":
            message = f"training {message}" if not message.startswith(("done", "starting")) else message
        self._job.update(progress=None if progress is None else lo + (hi - lo) * progress, step=step, total=total, message=message)

    def __getattr__(self, k):
        return getattr(self._job, k)

    def __setattr__(self, k, val):
        setattr(self._job, k, val)


QUICK_TYPES = {"character": "character", "style": "style", "concept": "concept", "outfit": "concept", "thing": "concept"}


def run_quick(job: Job, name: str, kind: str, ckpt: str):
    """One-click LoRA: caption the images that have no caption (trigger = name), then train."""
    preset = QUICK_TYPES.get(kind, "character")
    job.update(progress=0, message="preparing ...")
    ds.autocaption(_Phase(job, 0.0, 0.1, "tagging"), name, name, 0.35, False)
    job.check()
    job.update(progress=0.1, message="training: starting ...")
    run(_Phase(job, 0.1, 1.0, "training"),
        {"dataset": name, "name": name, "base_checkpoint": ckpt, "preset": preset, "trigger": name,
         "prune_core": preset != "style"})
