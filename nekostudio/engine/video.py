"""Video generation with Wan 2.1 via diffusers. torch is imported lazily."""
from __future__ import annotations

import json
import random
import sys
import time
import uuid

from .. import config
from ..jobs import Job
from . import image as image_engine

_state: dict = {"id": None, "pipe": None}


def list_models() -> list[dict]:
    return [{"id": m["id"], "label": m.get("label", m["id"])} for m in config.load_settings()["video_models"]]


def unload():
    _state.update(id=None, pipe=None)
    import gc
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


def _load(job: Job, model_id: str):
    import torch
    if _state["id"] == model_id and _state["pipe"] is not None:
        return _state["pipe"]
    if not torch.cuda.is_available():
        raise RuntimeError("No CUDA GPU available. Video generation needs an NVIDIA GPU.")
    image_engine.unload()  # only one big model in VRAM at a time
    unload()
    job.update(message="loading video model (first run downloads several GB)...")
    from diffusers import AutoencoderKLWan, WanImageToVideoPipeline, WanPipeline
    vae = AutoencoderKLWan.from_pretrained(model_id, subfolder="vae", torch_dtype=torch.float32)
    cls = WanImageToVideoPipeline if "i2v" in model_id.lower() else WanPipeline
    pipe = cls.from_pretrained(model_id, vae=vae, torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()  # the only way 12 GB holds a Wan model
    pipe.set_progress_bar_config(disable=True)
    _state.update(id=model_id, pipe=pipe)
    return pipe


def run(job: Job, p: dict):
    import torch
    from diffusers.utils import export_to_video

    model_id = p.get("model") or config.load_settings()["video_models"][0]["id"]
    is_i2v = "i2v" in model_id.lower()
    init = image_engine.decode_data_url(p["init_image"]) if p.get("init_image") else None
    if is_i2v and init is None:
        raise RuntimeError("This is an image-to-video model: provide an init image.")
    if init is not None and not is_i2v:
        raise RuntimeError("An init image needs an I2V model (e.g. Wan2.1-I2V-14B-480P-Diffusers).")

    width = int(p.get("width") or 832) // 16 * 16
    height = int(p.get("height") or 480) // 16 * 16
    frames = max(5, (int(p.get("frames") or 33) - 1) // 4 * 4 + 1)  # Wan wants 4k+1 frames
    steps = int(p.get("steps") or 30)
    fps = int(p.get("fps") or 16)
    seed = int(p.get("seed", -1))
    if seed < 0:
        seed = random.randint(0, 2**32 - 1)

    pipe = _load(job, model_id)
    job.check()

    def cb(_pipe, i, _t, kw):
        job.check()
        job.update(progress=(i + 1) / steps, step=i + 1, total=steps, message=f"step {i + 1}/{steps}")
        return kw

    kwargs = dict(prompt=p.get("prompt", ""), negative_prompt=p.get("negative") or None, height=height, width=width,
                  num_frames=frames, num_inference_steps=steps, guidance_scale=float(p.get("cfg") or 5.0),
                  generator=torch.Generator("cpu").manual_seed(seed), callback_on_step_end=cb)
    if init is not None:
        kwargs["image"] = init.resize((width, height))
    job.update(message="generating...", step=0, total=steps, progress=0)
    out = pipe(**kwargs).frames[0]

    day = config.VIDEOS / time.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    vid = f"{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"
    mp4, thumb = day / f"{vid}.mp4", day / f"{vid}.jpg"
    job.update(message="encoding mp4...")
    export_to_video(out, str(mp4), fps=fps)
    first = out[0]
    if not hasattr(first, "save"):  # numpy frames
        from PIL import Image
        first = Image.fromarray((first * 255).clip(0, 255).astype("uint8")) if first.dtype.kind == "f" else Image.fromarray(first)
    first.convert("RGB").save(thumb, quality=88)
    meta = dict(id=vid, kind="video", model=model_id, prompt=p.get("prompt", ""), negative=p.get("negative", ""),
                width=width, height=height, frames=frames, fps=fps, steps=steps, cfg=kwargs["guidance_scale"],
                seed=seed, created=time.strftime("%Y-%m-%dT%H:%M:%S"))
    (day / f"{vid}.json").write_text(json.dumps(meta, indent=2), "utf-8")
    job.add_result(config.file_url(mp4), config.file_url(thumb), meta)
