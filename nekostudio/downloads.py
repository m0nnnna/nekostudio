"""Model downloads and imports. They run in the jobs "dl" lane, so they never block GPU work.

Single files stream to `<name>.part` and resume with HTTP Range after a cancel or a crash;
repo snapshots (video models, taggers) go through huggingface_hub into the HF cache.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from . import catalog, config
from .jobs import Job, jobs

SAFE_ONLY = "Only .safetensors files can be imported (.ckpt/.pt files are pickles and can run code)."
CIVITAI_AUTH = "Civitai needs an API token, add it in Settings."
MARGIN = 256 * 1024 * 1024
KINDS = {"checkpoint": config.CHECKPOINTS, "lora": config.LORAS, "vae": config.VAES}
_active: dict[str, str] = {}   # catalog id -> job id


class DownloadError(RuntimeError):
    pass


def free_gb(path: Path = config.MODELS) -> float:
    return round(shutil.disk_usage(path).free / 1e9, 1)


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f} GB"


def _progress_text(done: int, total: int) -> str:
    if total >= 1e9 or done >= 1e9:
        return f"{done / 1e9:.1f} / {total / 1e9:.1f} GB" if total else f"{done / 1e9:.1f} GB"
    return f"{done / 1e6:.0f} / {total / 1e6:.0f} MB" if total else f"{done / 1e6:.0f} MB"


def check_space(folder: Path, need: int):
    free = shutil.disk_usage(folder).free
    if free < need + MARGIN:
        raise DownloadError(f"Not enough disk space: need {_gb(need + MARGIN)} but only {_gb(free)} is free on this drive.")


# ---- safetensors validation ------------------------------------------------------------------

def validate_safetensors(path: Path):
    """Parse the safetensors header (8-byte length + JSON) and check the tensor offsets fit the file."""
    size = path.stat().st_size
    try:
        with open(path, "rb") as f:
            raw = f.read(8)
            if len(raw) < 8:
                raise ValueError("file too small")
            n = int.from_bytes(raw, "little")
            if n <= 0 or n > 100_000_000 or 8 + n > size:
                raise ValueError("bad header length")
            header = json.loads(f.read(n))
        if not isinstance(header, dict):
            raise ValueError("header is not an object")
        end = 0
        for k, t in header.items():
            if k == "__metadata__":
                continue
            end = max(end, int(t["data_offsets"][1]))
        if 8 + n + end > size:
            raise ValueError("file is truncated")
    except (ValueError, KeyError, TypeError, IndexError, OSError) as e:
        raise DownloadError(f"Not a valid .safetensors file ({e}).") from e


def clean_name(name: str) -> str:
    name = Path(unquote(name or "").replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._+() -]", "_", name).strip(" .")
    return name[:150]


def check_ext(name: str):
    if not name.lower().endswith(".safetensors"):
        raise DownloadError(SAFE_ONLY)


def unique(folder: Path, name: str) -> Path:
    p, stem, n = folder / name, Path(name).stem, 1
    while p.exists():
        p = folder / f"{stem}_{n}.safetensors"
        n += 1
    return p


# ---- streaming one file ----------------------------------------------------------------------

def _disposition_name(cd: str) -> str:
    m = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", cd or "", re.I)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd or "", re.I)
    return m.group(1).strip() if m else ""


def _auth_error(r: httpx.Response, url: str):
    host = urlparse(url).hostname or ""
    if "civitai" in host:
        raise DownloadError(CIVITAI_AUTH)
    raise DownloadError(f"{host} refused access (HTTP {r.status_code}); the file is private or gated.")


def fetch(job: Job, url: str, folder: Path, headers: dict | None = None, name: str = "", hint: str = "",
          safetensors_only: bool = True) -> Path:
    """Download `url` into `folder`, resuming a previous `.part`. Returns the final path."""
    headers = {"Accept-Encoding": "identity", **(headers or {})}   # byte counts must match content-length
    client = httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=60.0),
                          headers={"User-Agent": "nekostudio"})
    try:
        job.update(message="connecting ...")
        ctx = client.stream("GET", url, headers=headers)
        r = ctx.__enter__()
        try:
            if r.status_code in (401, 403):
                _auth_error(r, url)
            if r.status_code >= 400:
                raise DownloadError(f"Server answered HTTP {r.status_code} for {urlparse(url).hostname}.")
            if "text/html" in r.headers.get("content-type", ""):
                if "civitai" in (urlparse(str(r.url)).hostname or ""):
                    raise DownloadError(CIVITAI_AUTH)
                raise DownloadError("That link is a web page, not a file. Use a direct download link.")
            fname = clean_name(name) or clean_name(_disposition_name(r.headers.get("content-disposition", ""))) \
                or clean_name(hint) or clean_name(urlparse(str(r.url)).path) or clean_name(urlparse(url).path)
            if name and safetensors_only and "." not in fname:
                fname += ".safetensors"
            if safetensors_only:
                check_ext(fname)
            total_full = int(r.headers.get("content-length") or 0)
            final_name = fname
            part = folder / (final_name + ".part")
            have = part.stat().st_size if part.exists() else 0
            if have and total_full and have > total_full:
                part.unlink()
                have = 0
            if have and (total_full == have):
                # a finished .part from an earlier run
                r.close()
                return _finish(part, folder, final_name, safetensors_only)
            if have:
                r.close()
                ctx.__exit__(None, None, None)
                ctx = client.stream("GET", url, headers={**headers, "Range": f"bytes={have}-"})
                r = ctx.__enter__()
                if r.status_code == 416:
                    part.unlink(missing_ok=True)
                    have = 0
                    r.close()
                    ctx.__exit__(None, None, None)
                    ctx = client.stream("GET", url, headers=headers)
                    r = ctx.__enter__()
                elif r.status_code in (401, 403):
                    _auth_error(r, url)
            total = 0
            if r.status_code == 206:
                m = re.search(r"/(\d+)\s*$", r.headers.get("content-range", ""))
                total = int(m.group(1)) if m else have + int(r.headers.get("content-length") or 0)
            else:
                have = 0     # server ignored Range (or fresh start): write from the beginning
                total = int(r.headers.get("content-length") or 0)
            check_space(folder, max(total - have, 0))
            done, last = have, 0.0
            with open(part, "ab" if have else "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    job.check()
                    f.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last > 0.25:
                        last = now
                        job.update(progress=done / total if total else 0, step=done, total=total,
                                   message=_progress_text(done, total))
            if total and done != total:
                raise DownloadError(f"Download ended early ({_progress_text(done, total)}); start it again to resume.")
        finally:
            ctx.__exit__(None, None, None)
    except httpx.HTTPError as e:
        raise DownloadError(f"Network error: {e}. Start it again to resume.") from e
    finally:
        client.close()
    return _finish(part, folder, final_name, safetensors_only)


def _finish(part: Path, folder: Path, name: str, validate: bool) -> Path:
    if validate:
        try:
            validate_safetensors(part)
        except DownloadError:
            part.unlink(missing_ok=True)
            raise
    dest = unique(folder, name) if name.lower().endswith(".safetensors") else folder / name
    os.replace(part, dest)
    return dest


# ---- catalog entries -------------------------------------------------------------------------

def _snapshot(job: Job, entry: dict):
    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import tqdm as hf_tqdm

    check_space(config.HF_HOME, int(entry["size_gb"] * 1e9))
    bars: list = []
    last = [0.0]

    class Bar(hf_tqdm):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            # byte bars only; "Reconstructing" is xet's second view of the same bytes
            if kw.get("unit") == "B" and not str(kw.get("desc") or "").startswith("Reconstructing"):
                bars.append(self)

        def update(self, n=1):
            r = super().update(n)
            job.check()
            now = time.monotonic()
            if self in bars and now - last[0] > 0.25:
                last[0] = now
                done, tot = sum(b.n for b in bars), sum(b.total or 0 for b in bars)
                tot = max(tot, done)
                job.update(progress=done / tot if tot else 0, step=int(done), total=int(tot), message=_progress_text(int(done), int(tot)))
            return r

    job.update(message="connecting ...")
    kw = {}
    if entry.get("only"):
        kw["allow_patterns"] = entry["only"]
    if entry.get("skip"):
        kw["ignore_patterns"] = entry["skip"]
    # One file at a time: the models drive may not like many parallel writers.
    snapshot_download(entry["repo"], tqdm_class=Bar, max_workers=1, **kw)


def _run_catalog(job: Job, entry: dict):
    try:
        if entry["file"]:
            url = entry.get("url") or f"https://huggingface.co/{entry['repo']}/resolve/main/{entry['file']}"
            # one stream, one file at a time (the "dl" lane is single-threaded); only checkpoints are safetensors
            dest = fetch(job, url, catalog.KIND_DIRS[entry["kind"]], name=entry.get("dest") or entry["file"].split("/")[-1],
                         safetensors_only=entry["kind"] in ("checkpoint", "lora", "vae"))
        else:
            _snapshot(job, entry)
            dest = None
    except DownloadError:
        raise
    job.add_result("", meta={"kind": entry["kind"], "name": dest.name if dest else entry["repo"], "id": entry["id"]})
    job.update(progress=1, message=f"installed {entry['label']}")


def start_catalog(entry_id: str) -> Job:
    entry = catalog.BY_ID.get(entry_id)
    if not entry:
        raise KeyError(entry_id)
    cur = jobs.get(_active.get(entry_id, ""))
    if cur and cur.state in ("queued", "running"):
        return cur
    if catalog.installed(entry):
        raise DownloadError(f"{entry['label']} is already installed.")
    job = jobs.submit("download", lambda j: _run_catalog(j, entry), lane="dl")
    job.update(message=f"queued: {entry['label']}")
    _active[entry_id] = job.id
    return job


def active_job(entry_id: str) -> str | None:
    j = jobs.get(_active.get(entry_id, ""))
    return j.id if j and j.state in ("queued", "running") else None


# ---- generic URL import ----------------------------------------------------------------------

def normalize_hf(url: str) -> str:
    u = urlparse(url)
    m = re.match(r"^/([^/]+/[^/]+)/blob/(.+)$", u.path)
    if m:
        return f"https://huggingface.co/{m.group(1)}/resolve/{m.group(2)}"
    return url


def _civitai(url: str, token: str) -> tuple[str, str]:
    """Resolve a civitai model page to (download url, file name)."""
    u = urlparse(url)
    m = re.match(r"^/models/(\d+)", u.path)
    if not m:
        return url, ""
    want = (parse_qs(u.query).get("modelVersionId") or [""])[0]
    h = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = httpx.get(f"https://civitai.com/api/v1/models/{m.group(1)}", headers=h, timeout=30, follow_redirects=True)
    except httpx.HTTPError as e:
        raise DownloadError(f"Could not reach civitai.com: {e}") from e
    if r.status_code in (401, 403):
        raise DownloadError(CIVITAI_AUTH)
    if r.status_code == 404:
        raise DownloadError("Civitai model not found.")
    r.raise_for_status()
    versions = r.json().get("modelVersions") or []
    ver = next((v for v in versions if str(v.get("id")) == want), None) or (versions[0] if versions else None)
    if not ver:
        raise DownloadError("That Civitai model has no downloadable version.")
    files = [f for f in ver.get("files", []) if str(f.get("name", "")).lower().endswith(".safetensors")]
    if not files:
        raise DownloadError("That Civitai version has no .safetensors file. " + SAFE_ONLY)
    f = next((x for x in files if x.get("primary")), files[0])
    return f["downloadUrl"], f.get("name", "")


def _run_import(job: Job, url: str, kind: str, name: str):
    host = (urlparse(url).hostname or "").lower()
    hint, headers = "", {}
    if host.endswith("huggingface.co"):
        url = normalize_hf(url)
        tok = os.environ.get("HF_TOKEN")
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
    elif host.endswith("civitai.com"):
        token = (config.load_settings().get("civitai_token") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        job.update(message="looking up Civitai ...")
        url, hint = _civitai(url, token)
    dest = fetch(job, url, KINDS[kind], headers=headers, name=name, hint=hint)
    job.add_result("", meta={"kind": kind, "name": dest.name})
    job.update(progress=1, message=f"imported {dest.name}")


def start_import(url: str, kind: str, name: str = "") -> Job:
    u = urlparse((url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise DownloadError("Paste a full http(s) link.")
    if kind not in KINDS:
        raise DownloadError("kind must be checkpoint, lora or vae.")
    if name:
        check_ext(clean_name(name) if "." in clean_name(name) else clean_name(name) + ".safetensors")
    path_ext = Path(u.path).suffix.lower()
    if path_ext in (".ckpt", ".pt", ".pth", ".bin", ".pkl"):
        raise DownloadError(SAFE_ONLY)
    job = jobs.submit("import", lambda j: _run_import(j, url.strip(), kind, name or ""), lane="dl")
    job.update(message="queued")
    return job


def save_upload(fileobj, filename: str, kind: str) -> Path:
    """Store an uploaded .safetensors in the models folder after validating its header."""
    if kind not in KINDS:
        raise DownloadError("kind must be checkpoint, lora or vae.")
    name = clean_name(filename)
    check_ext(name)
    folder = KINDS[kind]
    part = folder / (name + ".part")
    try:
        with open(part, "wb") as out:
            shutil.copyfileobj(fileobj, out, 1 << 20)
        validate_safetensors(part)
    except OSError as e:
        part.unlink(missing_ok=True)
        raise DownloadError(f"Could not save the file: {e}") from e
    except DownloadError:
        part.unlink(missing_ok=True)
        raise
    dest = unique(folder, name)
    os.replace(part, dest)
    return dest


def delete_lora(name: str):
    base = config.LORAS.resolve()
    p = (base / name).resolve()
    if base not in p.parents or p.suffix.lower() not in (".safetensors", ".ckpt") or not p.is_file():
        raise FileNotFoundError(name)
    p.unlink()
