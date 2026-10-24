"""Local prompt translator: a small instruct GGUF through llama.cpp (llama-cpp-python).

CPU by default (n_gpu_layers=0) so it never competes with SDXL for VRAM; the settings key
`llm_gpu_layers` offloads layers (-1 = all). The model loads on first use, stays resident and is
unloaded after IDLE_SECONDS without a request. The fixed system prompt + few-shots are a stable
prefix, so llama.cpp reuses its KV cache and only the new prose is processed per request.
"""
from __future__ import annotations

import os
import threading

from .. import config
from . import llm, postproc

IDLE_SECONDS = 600
PREFERRED = ("Qwen3-4B-Instruct-2507",)

_lock = threading.Lock()
_model = None
_loaded_with: tuple | None = None
_timer: threading.Timer | None = None


def model_path():
    files = sorted(config.LLMS.glob("*.gguf")) if config.LLMS.is_dir() else []
    for pref in PREFERRED:
        for f in files:
            if f.name.startswith(pref):
                return f
    return files[0] if files else None


def runtime_available() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def available() -> bool:
    return model_path() is not None and runtime_available()


def physical_cores() -> int:
    try:
        import psutil
        n = psutil.cpu_count(logical=False)
        if n:
            return n
    except Exception:  # noqa: BLE001
        pass
    return max(1, (os.cpu_count() or 2) // 2)


def loaded() -> bool:
    return _model is not None


def unload():
    global _model, _loaded_with
    with _lock:
        _model, _loaded_with = None, None


def _touch():
    global _timer
    if _timer:
        _timer.cancel()
    _timer = threading.Timer(IDLE_SECONDS, unload)
    _timer.daemon = True
    _timer.start()


def _get():
    global _model, _loaded_with
    layers = int(config.load_settings().get("llm_gpu_layers", 0) or 0)
    path = model_path()
    if path is None:
        raise FileNotFoundError("no GGUF model in " + str(config.LLMS))
    key = (str(path), layers)
    if _model is None or _loaded_with != key:
        from llama_cpp import Llama
        _model = None
        _model = Llama(model_path=str(path), n_ctx=4096, n_threads=physical_cores(), n_gpu_layers=layers,
                       n_batch=512, verbose=False)
        _loaded_with = key
    return _model


def generate(text: str) -> dict:
    with _lock:
        m = _get()
        try:
            out = m.create_chat_completion(
                messages=llm.messages(text), temperature=0.2, top_p=0.9, max_tokens=700,
                response_format={"type": "json_object", "schema": llm.SCHEMA})
        finally:
            _touch()
    return llm.parse(out["choices"][0]["message"]["content"])


def translate(text: str, source: str, rating: str) -> dict:
    res = postproc.finish(generate(text), text, source, rating)
    res["engine"] = "local"
    return res
