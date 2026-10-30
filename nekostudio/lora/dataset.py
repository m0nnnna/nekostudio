"""Dataset folders (images + same-name .txt captions) and WD14 auto-captioning."""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

from .. import config
from ..jobs import Job

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
TAGGERS = ["SmilingWolf/wd-eva02-large-tagger-v3", "SmilingWolf/wd-vit-tagger-v3"]


class DatasetError(ValueError):
    pass


def _dir(name: str, must_exist: bool = True) -> Path:
    if not NAME_RE.match(name or "") or ".." in name:
        raise DatasetError("Dataset name may only contain letters, digits, '_', '-' and '.'.")
    d = config.DATASETS / name
    if must_exist and not d.is_dir():
        raise DatasetError(f"Dataset '{name}' does not exist.")
    return d


def _images(d: Path) -> list[Path]:
    return sorted(p for p in d.iterdir() if p.suffix.lower() in IMG_EXT and p.is_file())


def _caption_path(img: Path) -> Path:
    return img.with_suffix(".txt")


def _meta(d: Path) -> dict:
    try:
        return json.loads((d / "meta.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def set_trigger(name: str, trigger: str):
    d = _dir(name)
    m = _meta(d)
    m["trigger"] = (trigger or "").strip()
    (d / "meta.json").write_text(json.dumps(m), "utf-8")


def list_datasets() -> list[dict]:
    out = []
    for d in sorted(p for p in config.DATASETS.iterdir() if p.is_dir()):
        imgs = _images(d)
        out.append({"name": d.name, "images": len(imgs),
                    "captioned": sum(1 for i in imgs if _caption_path(i).exists())})
    return out


def create(name: str) -> dict:
    d = _dir(name, must_exist=False)
    d.mkdir(parents=True, exist_ok=True)
    return get(name)


def get(name: str) -> dict:
    d = _dir(name)
    items = []
    for img in _images(d):
        cp = _caption_path(img)
        items.append({"file": img.name, "url": config.file_url(img),
                      "caption": cp.read_text("utf-8").strip() if cp.exists() else ""})
    return {"name": name, "trigger": _meta(d).get("trigger", ""), "items": items}


def add_file(name: str, filename: str, data: bytes) -> str | None:
    """Validate and store one uploaded image; returns the stored name or None if it is not an image."""
    from PIL import Image
    d = _dir(name)
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:  # noqa: BLE001
        return None
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(filename or "image").stem)[:60] or "image"
    ext = Path(filename or "").suffix.lower()
    ext = ext if ext in IMG_EXT else ".png"
    target, n = d / f"{stem}{ext}", 1
    while target.exists():
        target = d / f"{stem}_{n}{ext}"
        n += 1
    target.write_bytes(data)
    return target.name


def _file(name: str, file: str) -> Path:
    d = _dir(name)
    p = d / Path(file).name  # strip any directory part
    if not p.is_file():
        raise DatasetError(f"No such file: {file}")
    return p


def set_caption(name: str, file: str, caption: str):
    _caption_path(_file(name, file)).write_text((caption or "").strip(), "utf-8")


def delete_item(name: str, file: str):
    img = _file(name, file)
    _caption_path(img).unlink(missing_ok=True)
    img.unlink()


# ---- WD14 tagger -----------------------------------------------------------------------------

def _load_tagger(job: Job, cpu: bool = False):
    import onnxruntime as ort
    from huggingface_hub import hf_hub_download

    last = None
    for repo in TAGGERS:
        try:
            job.update(message=f"loading tagger {repo.split('/')[1]}...")
            model = hf_hub_download(repo, "model.onnx")
            tags_csv = hf_hub_download(repo, "selected_tags.csv")
            break
        except Exception as e:  # noqa: BLE001
            last = e
    else:
        raise RuntimeError(f"Could not download a WD14 tagger: {last}")
    avail = ort.get_available_providers()
    providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in avail and not (cpu and p.startswith("CUDA"))]
    sess = ort.InferenceSession(model, providers=providers)
    import csv
    with open(tags_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return sess, rows


def _prep(img, size: int):
    import numpy as np
    from PIL import Image
    img = img.convert("RGBA")
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    bg.alpha_composite(img)
    img = bg.convert("RGB")
    side = max(img.size)
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    canvas = canvas.resize((size, size), Image.BICUBIC)
    arr = np.asarray(canvas, dtype=np.float32)[:, :, ::-1]  # WD14 expects BGR 0..255
    return np.ascontiguousarray(arr[None])


def tag_image(sess, rows, img, threshold: float = 0.35) -> list[tuple[str, float]]:
    """WD14 tags of one PIL image as (tag, confidence), best first; underscores become spaces."""
    inp = sess.get_inputs()[0]
    probs = sess.run(None, {inp.name: _prep(img, inp.shape[1])})[0][0]
    scored = []
    for r, pr in zip(rows, probs):
        cat = int(r["category"])
        # category 0 = general, 4 = character; character tags need a higher bar
        if (cat == 0 and pr >= threshold) or (cat == 4 and pr >= 0.85):
            tag = r["name"]
            scored.append((tag.replace("_", " ") if len(tag) > 3 else tag, float(pr)))
    scored.sort(key=lambda t: -t[1])
    return scored


def autocaption(job: Job, name: str, trigger: str = "", threshold: float = 0.35, overwrite: bool = False):
    from PIL import Image
    d = _dir(name)
    if trigger:
        set_trigger(name, trigger)
    trigger = (trigger or _meta(d).get("trigger", "")).strip()
    todo = [i for i in _images(d) if overwrite or not _caption_path(i).exists()]
    if not todo:
        job.update(message="nothing to caption")
        return
    sess, rows = _load_tagger(job)
    for n, img_path in enumerate(todo, 1):
        job.check()
        tags = [t for t, _ in tag_image(sess, rows, Image.open(img_path), threshold)]
        if trigger and trigger not in tags:
            tags.insert(0, trigger)
        _caption_path(img_path).write_text(", ".join(tags), "utf-8")
        job.update(progress=n / len(todo), step=n, total=len(todo), message=f"captioned {n}/{len(todo)}")
