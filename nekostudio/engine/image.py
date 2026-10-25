"""Image generation with diffusers (SDXL / Pony / Illustrious / SD1.5). torch is imported lazily."""
from __future__ import annotations

import base64
import gc
import io
import json
import os
import random
import re
import struct
import sys
import threading
import time
import uuid
from pathlib import Path

from .. import config
from ..jobs import Job

PONY_POS = "score_9, score_8_up, score_7_up, "
PONY_NEG = "score_6, score_5, score_4, "

_state: dict = {"key": None, "pipe": None, "kind": None, "sched": None, "loras": (), "offload": False}
_lock = threading.Lock()
_kind_cache: dict = {}


# ---- model discovery (no torch needed) -------------------------------------------------------

def detect_kind(path: Path) -> str:
    """Peek at the safetensors header to tell SDXL from SD1.5 without loading weights."""
    try:
        key = (str(path), path.stat().st_mtime)
        if key in _kind_cache:
            return _kind_cache[key]
        with open(path, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            if n > 200_000_000:
                return "unknown"
            header = json.loads(f.read(n))
        names = " ".join(header.keys())
        kind = "unknown"
        if "conditioner.embedders.1" in names or "text_encoder_2" in names:
            kind = "sdxl"
        elif "cond_stage_model.transformer" in names or "text_model.encoder" in names:
            kind = "sd15"
        _kind_cache[key] = kind
        return kind
    except Exception:  # noqa: BLE001 - unreadable file is simply "unknown"
        return "unknown"


def _scan(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in (".safetensors", ".ckpt") and p.is_file())


def list_checkpoints() -> list[dict]:
    out = []
    for p in _scan(config.CHECKPOINTS):
        name = p.relative_to(config.CHECKPOINTS).as_posix()
        out.append({"name": name, "path": str(p), "kind": detect_kind(p), "pony": "pony" in name.lower()})
    return out


def list_loras() -> list[dict]:
    out = []
    for p in _scan(config.LORAS):
        item = {"name": p.relative_to(config.LORAS).as_posix(), "path": str(p), "trigger": "", "base": ""}
        side = p.with_suffix(".json")  # written by our trainer
        if side.is_file():
            try:
                d = json.loads(side.read_text("utf-8"))
                item.update(trigger=str(d.get("trigger") or ""), base=str(d.get("base") or ""))
            except (OSError, ValueError):
                pass
        out.append(item)
    return out


def list_vaes() -> list[dict]:
    return [{"name": p.relative_to(config.VAES).as_posix()} for p in _scan(config.VAES)]


# ---- pipeline management ---------------------------------------------------------------------

def unload():
    """Drop the cached pipeline and free VRAM (called before training)."""
    with _lock:
        _state.update(key=None, pipe=None, kind=None, sched=None, loras=())
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


def _use_offload(torch) -> bool:
    mode = config.load_settings().get("vram_mode", "auto")
    if mode == "low":
        return True
    if mode == "high":
        return False
    total = torch.cuda.get_device_properties(0).total_memory / 2**30
    return total < 10


def _resolve(name: str, folder: Path) -> str:
    """Local file under `folder` if it exists, otherwise the string is treated as a HF repo id."""
    p = (folder / name)
    return str(p) if p.is_file() else name


def _load_pipe(job: Job, ckpt: str, vae: str | None):
    import torch
    from diffusers import (AutoencoderKL, AutoPipelineForText2Image, StableDiffusionPipeline,
                           StableDiffusionXLPipeline)

    if not torch.cuda.is_available():
        raise RuntimeError("No CUDA GPU available (torch cannot see one). Image generation needs an NVIDIA GPU.")
    path = _resolve(ckpt, config.CHECKPOINTS)
    vae_path = _resolve(vae, config.VAES) if vae else None
    offload = _use_offload(torch)
    key = (path, vae_path, offload)
    if _state["key"] == key and _state["pipe"] is not None:
        return _state["pipe"]

    unload()
    job.update(message="loading checkpoint...")
    dt = torch.float16
    if os.path.isfile(path):
        kind = detect_kind(Path(path))
        if kind == "sd15":
            pipe = StableDiffusionPipeline.from_single_file(path, torch_dtype=dt, safety_checker=None)
        else:
            pipe = StableDiffusionXLPipeline.from_single_file(path, torch_dtype=dt)
            kind = "sdxl"
    else:
        try:
            pipe = AutoPipelineForText2Image.from_pretrained(path, torch_dtype=dt, variant="fp16")
        except Exception:  # noqa: BLE001 - repo without fp16 variant
            pipe = AutoPipelineForText2Image.from_pretrained(path, torch_dtype=dt)
        kind = "sdxl" if "XL" in type(pipe).__name__ else "sd15"
    if vae_path:
        v = AutoencoderKL.from_single_file(vae_path, torch_dtype=dt) if os.path.isfile(vae_path) \
            else AutoencoderKL.from_pretrained(vae_path, torch_dtype=dt)
        pipe.vae = v
    if offload:
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")
    # Decode the latents in slices/tiles: the fp32 VAE upcast at 1024px is what runs a 12 GB card out of memory.
    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()
    if hasattr(pipe.vae, "tile_sample_min_size"):  # default tile is 1024px, so 1024px images never got tiled
        pipe.vae.tile_sample_min_size = 512
        pipe.vae.tile_latent_min_size = 64
    if vae_path and "fp16-fix" in vae_path.lower():
        pipe.vae.config.force_upcast = False  # the fp16-fix VAE decodes fine in half precision
    pipe.set_progress_bar_config(disable=True)
    with _lock:
        _state.update(key=key, pipe=pipe, kind=kind, sched=dict(pipe.scheduler.config), loras=())
    return pipe


def _auto_vae(ckpt: str) -> str | None:
    """SDXL checkpoints get the fp16-fix VAE when it is installed: no fp32 upcast, no black images."""
    path = config.CHECKPOINTS / ckpt
    if not path.is_file() or detect_kind(path) != "sdxl":
        return None
    return next((v["name"] for v in list_vaes() if "fp16-fix" in v["name"].lower()), None)


def _set_sampler(pipe, name: str):
    from diffusers import (DDIMScheduler, DPMSolverMultistepScheduler, EulerAncestralDiscreteScheduler,
                           EulerDiscreteScheduler, UniPCMultistepScheduler)
    cfg = dict(_state["sched"])
    table = {
        "euler_a": (EulerAncestralDiscreteScheduler, {}),
        "euler": (EulerDiscreteScheduler, {}),
        "dpmpp_2m": (DPMSolverMultistepScheduler, {}),
        "dpmpp_2m_karras": (DPMSolverMultistepScheduler, {"use_karras_sigmas": True}),
        "dpmpp_sde_karras": (DPMSolverMultistepScheduler,
                             {"use_karras_sigmas": True, "algorithm_type": "sde-dpmsolver++"}),
        "ddim": (DDIMScheduler, {}),
        "unipc": (UniPCMultistepScheduler, {}),
    }
    cls, extra = table.get(name, table["euler_a"])
    pipe.scheduler = cls.from_config(cfg, **extra)


def _apply_loras(pipe, loras: list[dict]):
    """Load requested LoRAs as named adapters; skip work when the set is unchanged."""
    wanted = [(l["name"], float(l.get("weight", 1.0))) for l in loras if l.get("name")]
    names = tuple(n for n, _ in wanted)
    if names != _state["loras"]:
        if _state["loras"]:
            pipe.unload_lora_weights()
        adapters = []
        for n, _ in wanted:
            path = _resolve(n, config.LORAS)
            adapter = re.sub(r"[^A-Za-z0-9_]", "_", Path(n).stem)
            pipe.load_lora_weights(path, adapter_name=adapter)
            adapters.append(adapter)
        _state["loras"] = names
        _state["adapters"] = adapters
    if wanted:
        pipe.set_adapters(_state["adapters"], adapter_weights=[w for _, w in wanted])


# ---- prompt helpers --------------------------------------------------------------------------

def apply_pony(prompt: str, negative: str, checkpoint: str, flag: bool | None) -> tuple[str, str, bool]:
    pony = bool(flag) or "pony" in (checkpoint or "").lower()
    if pony:
        if not prompt.lower().lstrip().startswith("score_9"):
            prompt = PONY_POS + prompt
        if "score_6" not in negative.lower():
            negative = PONY_NEG + negative
    return prompt, negative, pony


def decode_data_url(data: str):
    from PIL import Image
    raw = data.split(",", 1)[1] if data.startswith("data:") else data
    return Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")


# ---- main entry ------------------------------------------------------------------------------

def run(job: Job, p: dict):
    import torch

    steps = int(p.get("steps") or 28)
    width, height = int(p.get("width") or 1024) // 8 * 8, int(p.get("height") or 1024) // 8 * 8
    batch = max(1, min(8, int(p.get("batch") or 1)))
    seed = int(p.get("seed", -1))
    if seed < 0:
        seed = random.randint(0, 2**32 - 1)
    ckpt = p.get("checkpoint") or ""
    if not ckpt:
        raise RuntimeError("No checkpoint selected. Put a .safetensors file in data/models/checkpoints/.")

    prompt, negative, pony = apply_pony(p.get("prompt", ""), p.get("negative", ""), ckpt, p.get("pony"))
    clip_skip = p.get("clip_skip") or (2 if pony else 1)

    pipe = _load_pipe(job, ckpt, p.get("vae") or _auto_vae(ckpt))
    job.check()
    _set_sampler(pipe, p.get("sampler") or "euler_a")
    _apply_loras(pipe, p.get("loras") or [])

    init = decode_data_url(p["init_image"]).resize((width, height)) if p.get("init_image") else None
    if init is not None:
        from diffusers import AutoPipelineForImage2Image
        run_pipe = AutoPipelineForImage2Image.from_pipe(pipe)
    else:
        run_pipe = pipe

    def cb(_pipe, i, _t, kw):
        job.check()  # raises Cancelled
        total = getattr(_pipe, "num_timesteps", steps) or steps
        job.update(progress=(i + 1) / total, step=i + 1, total=total, message=f"step {i + 1}/{total}")
        return kw

    kwargs = dict(prompt=prompt, negative_prompt=negative or None, num_inference_steps=steps,
                  guidance_scale=float(p.get("cfg") or 7.0), num_images_per_prompt=batch,
                  generator=[torch.Generator("cpu").manual_seed(seed + i) for i in range(batch)],
                  callback_on_step_end=cb)
    # A1111 clip skip N -> diffusers clip_skip. SD1.5 uses the last CLIP layer by default (skip 2 = 1), but
    # SDXL already uses the penultimate one (skip 2 = default); an extra skip there turns Pony into grey mush.
    extra_skip = int(clip_skip) - (2 if _state["kind"] == "sdxl" else 1)
    if extra_skip > 0:
        kwargs["clip_skip"] = extra_skip
    if init is not None:
        kwargs.update(image=init, strength=float(p.get("strength") or 0.6))
    else:
        kwargs.update(width=width, height=height)

    job.update(message="generating...", step=0, total=steps, progress=0)
    try:
        images = run_pipe(**kwargs).images
    except BaseException:
        # A failure mid-step (OOM, cancel during the VAE upcast) can leave the pipe half fp32; start clean next time.
        unload()
        raise
    _save(job, images, p, dict(prompt=prompt, negative=negative, seed=seed, pony=pony, clip_skip=int(clip_skip),
                               width=width, height=height))


def _save(job: Job, images, p: dict, extra: dict):
    from PIL.PngImagePlugin import PngInfo

    day = config.IMAGES / time.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    for i, img in enumerate(images):
        iid = f"{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"
        meta = {k: p.get(k) for k in ("checkpoint", "vae", "loras", "steps", "cfg", "sampler", "batch", "strength")}
        meta.update(extra, seed=extra["seed"] + i, id=iid, kind="image", created=time.strftime("%Y-%m-%dT%H:%M:%S"))
        info = PngInfo()
        info.add_text("parameters", f"{meta['prompt']}\nNegative prompt: {meta['negative']}\n"
                                    f"Steps: {meta['steps']}, Sampler: {meta['sampler']}, CFG scale: {meta['cfg']}, "
                                    f"Seed: {meta['seed']}, Size: {meta['width']}x{meta['height']}")
        png = day / f"{iid}.png"
        img.save(png, pnginfo=info)
        thumb = img.copy()
        thumb.thumbnail((384, 384))
        thumb.convert("RGB").save(day / f"{iid}.thumb.jpg", quality=85)
        (day / f"{iid}.json").write_text(json.dumps(meta, indent=2), "utf-8")
        job.add_result(config.file_url(png), config.file_url(day / f"{iid}.thumb.jpg"), meta)
