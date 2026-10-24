"""Translation front door: picks the engine (auto / local / rules / remote) and reports which one ran."""
from __future__ import annotations

from .. import config
from . import llm, local_llm, pony, postproc, tagdb

MODES = ("auto", "local", "rules", "remote")


def status() -> dict:
    """What the TRANSLATE page needs to offer: installed pieces and the download card."""
    from .. import catalog
    ids = ("tags-danbooru", "tags-e621", "qwen3-4b-instruct")
    missing = [catalog.BY_ID[i] for i in ids if not catalog.installed(catalog.BY_ID[i])]
    return {"local_ready": local_llm.available(), "runtime": local_llm.runtime_available(), "loaded": local_llm.loaded(),
            "tags_ready": tagdb.full(), "tag_sources": tagdb.sources() if tagdb.available() else [],
            "missing": [{"id": e["id"], "label": e["label"], "size_gb": e["size_gb"]} for e in missing],
            "missing_gb": round(sum(e["size_gb"] for e in missing), 2)}


def translate(text: str, mode: str = "auto", source: str = "anime", rating: str = "safe") -> dict:
    source = source if source in postproc.SOURCE_TAGS else "anime"
    rating = rating if rating in postproc.RATINGS else "safe"
    mode = {"llm": "remote"}.get(mode, mode)
    if mode not in MODES:
        mode = "auto"
    note = ""
    if mode in ("auto", "local"):
        if local_llm.available() and tagdb.available():
            try:
                return local_llm.translate(text, source, rating)
            except Exception as e:  # noqa: BLE001
                if mode == "local":
                    raise
                note = f"Local translator failed ({type(e).__name__}: {e}); used rules instead."
        elif mode == "local":
            raise RuntimeError("The local translator is not installed. Download it on the TRANSLATE page.")
        else:
            note = "Local translator not installed; using the rule-based fallback (download it on the TRANSLATE page for better results)."
    elif mode == "remote":
        try:
            return llm.translate_remote(text, source, rating, config.load_settings()["llm"])
        except Exception as e:  # noqa: BLE001
            note = f"Remote LLM failed ({type(e).__name__}: {e}); used rules instead."
    res = pony.translate(text, source, rating)
    if not tagdb.available():
        note = (note + " " if note else "") + "Tag lists are missing, results are limited: download them on the TRANSLATE page."
    res["note"] = note
    return res
