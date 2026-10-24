"""Optional prose -> Pony tags through any OpenAI-compatible chat endpoint."""
from __future__ import annotations

import httpx

from . import pony

SYSTEM = """You convert natural-language image descriptions into Pony Diffusion (SDXL) booru-style tags.
Rules: output ONE line of comma-separated lowercase tags and nothing else (no prose, no markdown).
Use danbooru vocabulary with spaces, not underscores (e.g. "long hair", "silver hair", "red eyes",
"looking at viewer", "cherry blossoms", "black kimono", "full body"). Start with the character count
(1girl, 1boy, 2girls...) and "solo" when there is exactly one character. Then describe hair, eyes,
expression, pose, clothing (colour + garment), setting, lighting, time of day and camera framing.
Do NOT output quality tags (masterpiece, best quality, highly detailed), score_*, source_* or rating_* tags:
those are added automatically. Do not invent content that the description does not imply."""


def translate_llm(text: str, source: str, rating: str, cfg: dict) -> dict:
    base = (cfg.get("base_url") or "").rstrip("/")
    model = cfg.get("model") or ""
    if not base or not model:
        raise ValueError("LLM base URL and model are not configured (Settings).")
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    body = {"model": model, "temperature": 0.2,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]}
    r = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=120)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    return pony.normalise_tag_list(content, source, rating)


def translate(text: str, source: str, rating: str, cfg: dict) -> dict:
    """LLM translation; on any failure fall back to the rule-based path and say so in `note`."""
    try:
        res = translate_llm(text, source, rating, cfg)
        if not res["tags"]:
            raise ValueError("empty response")
        return res
    except Exception as e:  # noqa: BLE001
        res = pony.translate(text, source, rating)
        res["note"] = f"LLM failed ({type(e).__name__}: {e}); used rule-based translation instead."
        return res
