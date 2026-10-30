"""FastAPI app: REST API under /api, generated files under /files, web UI at /."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import queue
import re
import shutil
import subprocess
import time
from datetime import datetime
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import __version__, catalog, config, downloads, updater
from .engine import image as image_engine
from .engine import outfit as outfit_engine
from .engine import video as video_engine
from .jobs import jobs
from .lora import dataset as ds
from .lora import train as trainer
from .prompts import local_llm, pony, tagdb, translate as translator

app = FastAPI(title="NekoStudio", version=__version__)
# What nekostudio-update installed: 0.1.0, or 0.1.0-3-gabc1234 for an --edge build.
INSTALLED = updater.installed().removeprefix("v")


# ---- request models (extra keys are tolerated so the UI can evolve) -------------------------

class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")


class LoraRef(_Base):
    name: str
    weight: float = 1.0


class ImageReq(_Base):
    prompt: str = ""
    negative: str = ""
    checkpoint: str = ""
    vae: Optional[str] = None
    loras: list[LoraRef] = Field(default_factory=list)
    width: int = 1024
    height: int = 1024
    steps: int = 28
    cfg: float = 6.0
    sampler: str = "euler_a"
    seed: int = -1
    batch: int = 1
    clip_skip: Optional[int] = None
    pony: Optional[bool] = None
    init_image: Optional[str] = None
    strength: Optional[float] = None


class OutfitReq(_Base):
    character: str                      # data URL of the character / reference sheet
    outfit: str                         # data URL of the outfit (on a faceless model or on its own)
    face_box: Optional[list[float]] = None   # x0, y0, x1, y1 as fractions of the character picture
    prompt: str = ""
    negative: str = ""
    checkpoint: str = ""
    vae: Optional[str] = None
    loras: list[LoraRef] = Field(default_factory=list)
    width: int = 832
    height: int = 1216
    steps: int = 28
    cfg: float = 6.0
    sampler: str = "euler_a"
    seed: int = -1
    batch: int = 1
    clip_skip: Optional[int] = None
    pony: Optional[bool] = None
    character_strength: float = 0.5
    outfit_strength: float = 0.6


class VideoReq(_Base):
    prompt: str = ""
    negative: str = ""
    model: str = ""
    width: int = 832
    height: int = 480
    frames: int = 33
    fps: int = 16
    steps: int = 30
    cfg: float = 5.0
    seed: int = -1
    init_image: Optional[str] = None


class TranslateReq(_Base):
    text: str
    mode: str = "auto"      # auto | local | rules | remote
    source: str = "anime"
    rating: str = "safe"


class NameReq(_Base):
    name: str


class CaptionReq(_Base):
    file: str
    caption: str = ""


class AutocaptionReq(_Base):
    trigger: Optional[str] = None
    threshold: float = 0.35
    overwrite: bool = False


class TrainReq(_Base):
    dataset: str
    name: str
    base_checkpoint: str
    preset: str = "character"
    trigger: str = ""
    overrides: Optional[dict] = None


def _ds_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ds.DatasetError as e:
        raise HTTPException(404 if "exist" in str(e) or "No such" in str(e) else 400, str(e))


# ---- status / models / settings -------------------------------------------------------------

_gpu_cache: dict[str, Any] = {"t": 0.0, "v": None}


def _gpu() -> Optional[dict]:
    if time.time() - _gpu_cache["t"] < 2:
        return _gpu_cache["v"]
    val = None
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=4)
            name, total, free = [x.strip() for x in out.stdout.strip().splitlines()[0].split(",")]
            val = {"name": name, "vram_total_mb": int(total), "vram_free_mb": int(free)}
        except Exception:  # noqa: BLE001
            val = None
    _gpu_cache.update(t=time.time(), v=val)
    return val


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


@app.get("/api/status")
def status():
    return {"version": INSTALLED, "gpu": _gpu(), "torch": _has("torch"), "diffusers": _has("diffusers"),
            "train_ready": config.train_ready(), "busy": jobs.busy, "queue": jobs.pending}


@app.get("/api/models")
def models():
    video = [dict(m, installed=catalog.video_installed(m["id"]), in_catalog=any(e["repo"] == m["id"] for e in catalog.CATALOG))
             for m in video_engine.list_models()]
    return {"checkpoints": image_engine.list_checkpoints(), "loras": image_engine.list_loras(),
            "vaes": image_engine.list_vaes(), "video": video, "ip_adapter": catalog.ip_adapter_dir() is not None}


@app.delete("/api/models/lora/{name:path}")
def delete_lora(name: str):
    try:
        downloads.delete_lora(name)
    except FileNotFoundError:
        raise HTTPException(404, "LoRA not found")
    return {"ok": True}


# ---- catalog / downloads / import -----------------------------------------------------------

class ImportReq(_Base):
    url: str
    kind: str = "checkpoint"
    name: Optional[str] = None


def _dl(fn, *a):
    try:
        return fn(*a)
    except downloads.DownloadError as e:
        raise HTTPException(400, str(e))


@app.get("/api/catalog")
def get_catalog():
    items = []
    for e in catalog.CATALOG:
        inst = catalog.installed(e)
        items.append({**catalog.public(e), "installed": inst, "job_id": None if inst else downloads.active_job(e["id"])})
    return {"items": items, "disk_free_gb": downloads.free_gb()}


@app.post("/api/catalog/{entry_id}/download")
def catalog_download(entry_id: str):
    if entry_id not in catalog.BY_ID:
        raise HTTPException(404, "unknown catalog entry")
    return {"job_id": _dl(downloads.start_catalog, entry_id).id}


@app.post("/api/import/url")
def import_url(req: ImportReq):
    return {"job_id": _dl(downloads.start_import, req.url, req.kind, req.name or "").id}


@app.post("/api/import/file")
def import_file(file: UploadFile = File(...), kind: str = Form("checkpoint")):
    dest = _dl(downloads.save_upload, file.file, file.filename or "", kind)
    return {"ok": True, "kind": kind, "name": dest.name}


@app.get("/api/settings")
def get_settings():
    return config.public_settings()


@app.put("/api/settings")
def put_settings(body: dict):
    config.save_settings(body)
    return config.public_settings()


# ---- generation / jobs ----------------------------------------------------------------------

@app.post("/api/generate/image")
def generate_image(req: ImageReq):
    p = req.model_dump()
    return {"job_id": jobs.submit("image", lambda job: image_engine.run(job, p)).id}


@app.post("/api/generate/outfit")
def generate_outfit(req: OutfitReq):
    p = req.model_dump()
    if p["face_box"] is not None and len(p["face_box"]) != 4:
        raise HTTPException(400, "face_box needs 4 numbers: x0, y0, x1, y1.")
    return {"job_id": jobs.submit("outfit", lambda job: outfit_engine.run(job, p)).id}


@app.post("/api/generate/video")
def generate_video(req: VideoReq):
    p = req.model_dump()
    return {"job_id": jobs.submit("video", lambda job: video_engine.run(job, p)).id}


@app.get("/api/jobs")
def list_jobs():
    """Queued and running jobs, so a reloaded page can pick them up again."""
    return [j.to_dict() for j in jobs.active()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    job.cancel()
    return {"ok": True}


@app.get("/api/events")
async def events(request: Request):
    q = jobs.subscribe()

    async def gen():
        idle = 0.0
        try:
            yield ": connected\n\n"
            while not await request.is_disconnected():
                try:
                    yield f"data: {json.dumps(q.get_nowait())}\n\n"
                    idle = 0.0
                except queue.Empty:
                    await asyncio.sleep(0.15)
                    idle += 0.15
                    if idle >= 15:
                        yield ": ping\n\n"
                        idle = 0.0
        finally:
            jobs.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- gallery --------------------------------------------------------------------------------

_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@app.get("/api/gallery")
def gallery(kind: str = "image", offset: int = 0, limit: int = 60):
    base = config.VIDEOS if kind == "video" else config.IMAGES
    metas = sorted(base.glob("*/*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    items = []
    for jp in metas[offset:offset + limit]:
        media = jp.with_suffix(".mp4" if kind == "video" else ".png")
        thumb = jp.with_suffix(".jpg" if kind == "video" else ".thumb.jpg")
        if not media.exists():
            continue
        try:
            meta = json.loads(jp.read_text("utf-8"))
        except ValueError:
            meta = {}
        items.append({"id": jp.stem, "kind": kind, "url": config.file_url(media),
                      "thumb": config.file_url(thumb if thumb.exists() else media), "meta": meta,
                      "created": datetime.fromtimestamp(jp.stat().st_mtime).isoformat(timespec="seconds")})
    return {"items": items, "total": len(metas)}


@app.delete("/api/gallery/{item_id}")
def gallery_delete(item_id: str):
    if not _ID_RE.match(item_id):
        raise HTTPException(400, "bad id")
    found = False
    for base in (config.IMAGES, config.VIDEOS):
        for jp in base.glob(f"*/{item_id}.json"):
            for f in jp.parent.glob(f"{item_id}.*"):
                f.unlink(missing_ok=True)
            found = True
    if not found:
        raise HTTPException(404, "not found")
    return {"ok": True}


# ---- translate ------------------------------------------------------------------------------

@app.get("/api/translate/status")
def translate_status():
    return translator.status()


@app.post("/api/translate")
def translate(req: TranslateReq):
    try:
        return translator.translate(req.text, req.mode, req.source, req.rating)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))


# ---- datasets / training --------------------------------------------------------------------

@app.get("/api/datasets")
def datasets_list():
    return ds.list_datasets()


@app.post("/api/datasets")
def datasets_create(req: NameReq):
    return _ds_call(ds.create, req.name)


@app.post("/api/datasets/{name}/upload")
async def datasets_upload(name: str, files: list[UploadFile] = File(..., alias="files[]")):
    added = 0
    for f in files:
        if _ds_call(ds.add_file, name, f.filename or "image", await f.read()):
            added += 1
    return {"added": added}


@app.get("/api/datasets/{name}")
def datasets_get(name: str):
    return _ds_call(ds.get, name)


@app.put("/api/datasets/{name}/caption")
def datasets_caption(name: str, req: CaptionReq):
    _ds_call(ds.set_caption, name, req.file, req.caption)
    return {"ok": True}


@app.delete("/api/datasets/{name}/item/{file}")
def datasets_delete_item(name: str, file: str):
    _ds_call(ds.delete_item, name, file)
    return {"ok": True}


@app.post("/api/datasets/{name}/autocaption")
def datasets_autocaption(name: str, req: AutocaptionReq):
    _ds_call(ds._dir, name)
    job = jobs.submit("caption", lambda j: ds.autocaption(j, name, req.trigger or "", req.threshold, req.overwrite))
    return {"job_id": job.id}


@app.post("/api/train")
def train(req: TrainReq):
    _ds_call(ds._dir, req.dataset)
    p = req.model_dump()
    job = jobs.submit("train", lambda job: trainer.run(job, p))
    job.info = {"flow": "wizard", "name": p.get("name") or ""}
    return {"job_id": job.id}


class QuickReq(_Base):
    name: str
    type: str = "character"
    base_checkpoint: str = ""


@app.post("/api/lora/quick")
def lora_quick(req: QuickReq):
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$", req.name or ""):
        raise HTTPException(400, "LoRA name may only contain letters, digits, '_' and '-'.")
    if not config.train_ready():
        raise HTTPException(400, "LoRA trainer is not installed. " + trainer.SETUP_HINT)
    d = _ds_call(ds._dir, req.name)
    if not ds._images(d):
        raise HTTPException(400, "Add some images first.")
    ckpt = req.base_checkpoint
    if not ckpt:
        cks = image_engine.list_checkpoints()
        pick = next((c for c in cks if c["pony"]), cks[0] if cks else None)
        ckpt = pick["name"] if pick else ""
    if not ckpt or not (config.CHECKPOINTS / ckpt).is_file():
        raise HTTPException(400, "Pick a base checkpoint (download one in MODELS).")
    job = jobs.submit("train", lambda job: trainer.run_quick(job, req.name, req.type, ckpt))
    job.info = {"flow": "quick", "name": req.name, "base": ckpt}
    return {"job_id": job.id}


# ---- static ---------------------------------------------------------------------------------

app.mount("/files/outputs", StaticFiles(directory=config.OUTPUTS), name="outputs")
app.mount("/files/datasets", StaticFiles(directory=config.DATASETS), name="datasets")

if (config.WEB_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
else:
    @app.get("/", response_class=HTMLResponse)
    def _placeholder():
        return "<h1>NekoStudio</h1><p>web/ is missing; the API is available under /api.</p>"
