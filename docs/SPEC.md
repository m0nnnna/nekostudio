# NEKOSTUDIO — spec

A local AI art studio: image + video generation, easy LoRA training, negative prompts, and a
GPT-prose → Pony-tags prompt translator. One Python server, one browser UI, styled exactly
like the Ultimit desktop (`docs/design/mockup.html` in m0nnnna/ultimit). Runs on Ubuntu and
Windows with an NVIDIA GPU (target: 12 GB VRAM, e.g. RTX 4070). Licence MIT.

## Layout

```
nekostudio/
  README.md  LICENSE  pyproject.toml  requirements.txt  requirements-train.txt
  setup.sh  run.sh                 # Ubuntu
  setup.ps1 run.ps1 setup.bat run.bat  # Windows (the .bat files just call the .ps1 with -ExecutionPolicy Bypass)
  nekostudio/                      # python package
    __init__.py  __main__.py       # `python -m nekostudio [--host 127.0.0.1] [--port 7860] [--open]`
    config.py                      # paths + settings.json load/save
    server.py                      # FastAPI app, REST API below, serves web/ at /
    jobs.py                        # job queue: "gpu" lane (one worker) + separate "dl" lane for downloads; progress, cancel
    catalog.py                     # ready-to-click model catalog (repo/file/size/note), installed detection
    downloads.py                   # resumable streaming downloads, URL/file import, safetensors validation
    engine/image.py                # diffusers SDXL/Pony/SD1.5 txt2img + img2img
    engine/video.py                # diffusers Wan2.1 T2V / I2V
    lora/dataset.py                # dataset folders, upload, auto-caption (WD14 tagger), caption edit
    lora/train.py                  # builds kohya sd-scripts TOML + launches it in the training venv
    prompts/pony.py                # rule-based prose → Pony tags
    prompts/llm.py                 # optional LLM translation via any OpenAI-compatible endpoint
  web/  index.html  style.css  app.js   # no build step, no framework, no CDN at runtime except Google Fonts (with local fallbacks)
  docs/SPEC.md
```

## Data directory

Default `./data` next to the repo (override with env `NEKOSTUDIO_HOME`). Created on start:

```
data/settings.json
data/models/checkpoints/   *.safetensors (SDXL, Pony, Illustrious, SD1.5 single files)
data/models/loras/         *.safetensors (trained LoRAs land here too)
data/models/vae/
data/outputs/images/YYYY-MM-DD/  <id>.png + <id>.json (all generation params)
data/outputs/videos/YYYY-MM-DD/  <id>.mp4 + <id>.json + <id>.jpg (first frame thumb)
data/datasets/<name>/      images + same-name .txt captions
data/training/<name>/      kohya config.toml, logs, sample images
data/hf/                   HF_HOME (model downloads)
```

## Backend rules

- Python 3.12 venv in `.venv` (setup creates it with `uv`). Torch CUDA 12.8 wheels.
- Server must start and serve the UI **without** a GPU or any model: import torch/diffusers
  lazily inside the engines. `/api/status` reports what is missing.
- Downloads and imports run in their own "dl" lane (own queue + worker thread), so they never wait for or
  block GPU jobs: you can generate while a model downloads.
- One GPU job at a time (`jobs.py`: a queue + one worker thread). Image/video/caption/train jobs
  all go through it. Training runs as a subprocess so it can be cancelled; while it runs the
  generation pipelines are unloaded to free VRAM.
- Image engine: `StableDiffusionXLPipeline.from_single_file` (or SD1.5 by detection) for local
  files, `from_pretrained` for HF repo ids. Keep the loaded pipe cached; reload only when the
  checkpoint changes. `enable_model_cpu_offload()` when VRAM < 10 GB, else `.to("cuda")`, fp16.
  LoRAs via `load_lora_weights` + `set_adapters(names, weights)`; unload when not used.
  Long prompts: use compel-free chunking is NOT required; just truncate silently is acceptable
  but prefer `sd_embed`-style chunking if cheap. Samplers: map names → diffusers schedulers:
  `euler_a` (EulerAncestral), `euler`, `dpmpp_2m`, `dpmpp_2m_karras`, `dpmpp_sde_karras`,
  `ddim`, `unipc`. Clip skip (Pony wants 2). Progress via `callback_on_step_end`; cancel by raising
  in the callback. Optional VAE file. img2img when `init_image` given.
- Pony auto-mode: if checkpoint filename contains `pony` (case-insensitive) or the request
  sets `pony: true`, prepend `score_9, score_8_up, score_7_up, ` to the prompt (unless already
  there) and `score_6, score_5, score_4, ` to the negative, and default clip_skip to 2.
- Video engine: `WanPipeline` with `Wan-AI/Wan2.1-T2V-1.3B-Diffusers` (default, fits 12 GB with
  cpu offload) and `Wan-AI/Wan2.1-I2V-14B-480P-Diffusers` listed as optional; models list comes
  from settings so more can be added. Output mp4 via `diffusers.utils.export_to_video`
  (imageio-ffmpeg). Negative prompt supported.
- LoRA training: kohya `sd-scripts` cloned by setup into `vendor/sd-scripts`, installed in a
  **separate** venv `.venv-train` (its pinned deps clash with current diffusers). `train.py`
  writes a dataset TOML + args, runs `sdxl_train_network.py` (or `train_network.py` for SD1.5),
  parses its stdout for `steps: N/M` and loss, and copies the result into `models/loras/`.
  Presets (UI shows only these + "advanced"): 
  - `character` (dim 16, alpha 16, lr 2e-4, 10 repeats, 10 epochs)
  - `style` (dim 32, alpha 16, lr 1.5e-4, 5 repeats, 12 epochs)
  - `concept` (dim 16, alpha 16, lr 2e-4, 8 repeats, 10 epochs)
  Quick LoRA (character/concept) drops tags present on ≥50% of images (except framing tags like
  `1girl`, `solo`, `upper body`) from the training copy of the captions, so the trigger word learns
  the subject's fixed look. No per-epoch sample images (they OOM a 12 GB card next to training).
  Always: AdamW8bit, cosine, gradient checkpointing, cache latents (to disk), mixed precision bf16,
  sdpa, resolution 1024 (SDXL) / 512 (SD1.5), bucketing on, batch 1, network_module networks.lora,
  save every epoch, `--no_half_vae` for SDXL. Trigger word is prepended to every caption.
- Auto-caption: WD14 tagger ONNX (`SmilingWolf/wd-eva02-large-tagger-v3`, fall back to
  `SmilingWolf/wd-vit-tagger-v3`) via onnxruntime-gpu (CPU fallback), threshold 0.35, booru tags
  with underscores → spaces, which is exactly the Pony tag style. Optional prefix trigger word.
- Prose → Pony (`prompts/pony.py`, no network): lowercase, split on `,` `.` `;` ` and ` ` with `,
  drop articles/filler ("a", "an", "the", "there is", "image of", "picture of", "showing",
  "featuring", "beautiful"→ keep as tag only if in a small adjective whitelist), map a phrase
  table (≥150 entries) of common prose → booru tags, e.g. "a girl/woman" → `1girl`, "two girls"
  → `2girls`, "a man" → `1boy`, "alone" → `solo`, "looking at the viewer" → `looking at viewer`,
  "smiling" → `smile`, "long blonde hair" → `long hair, blonde hair`, "blue eyes" → `blue eyes`,
  "at night" → `night`, "in a forest" → `forest, outdoors`, "close-up" → `close-up`,
  "from above" → `from above`, "full body shot" → `full body`, colour+garment
  ("red dress" → `red dress`), "cat ears", "highly detailed" → (dropped, Pony uses score tags),
  "anime style" → `anime`, "photorealistic" → `realistic, photorealistic`, etc. Add `solo` when
  exactly one character and no other people. Output order: score tags, source tag
  (`source_anime` / `source_cartoon` / `source_furry` / `source_pony` / realistic gets none),
  rating tag (`rating_safe` default, `rating_questionable`, `rating_explicit` — chosen by user,
  never guessed upward), character count, then the rest, deduped. Also returns a suggested
  negative prompt. Return `{"prompt", "negative", "tags": [...], "dropped": [...]}`.
- LLM mode (`prompts/llm.py`): POST to `{base_url}/chat/completions` (OpenAI-compatible: OpenAI,
  OpenRouter, Ollama `http://127.0.0.1:11434/v1`, LM Studio) with a system prompt that teaches
  Pony format; settings hold base_url, model, api_key (stored only in data/settings.json). Uses
  `httpx`. Result is post-processed by the same normaliser as the rule-based path. If it fails,
  fall back to rule-based and say so in `note`.

## REST API (all JSON, under /api)

| Method + path | Body / query | Returns |
|---|---|---|
| GET `/api/status` | | `{version, gpu:{name, vram_total_mb, vram_free_mb}\|null, torch:bool, diffusers:bool, train_ready:bool, busy:bool, queue:int}` |
| GET `/api/models` | | `{checkpoints:[{name, path, kind:"sdxl"\|"sd15"\|"unknown", pony:bool}], loras:[{name, path}], vaes:[{name}], video:[{id, label, installed, in_catalog}]}` |
| DELETE `/api/models/lora/{name}` | | `{ok}` (path-traversal safe; 404 if not a LoRA file) |
| GET/PUT `/api/settings` | settings object | settings object (api_key and civitai_token returned masked `"••••"` if set; PUT with `"••••"` keeps old) |
| GET `/api/catalog` | | `{items:[{id, label, kind:"checkpoint"\|"vae"\|"video"\|"tagger", family, repo, file, size_gb, note, recommended, installed, job_id\|null}], disk_free_gb}` |
| POST `/api/catalog/{id}/download` | | `{job_id}` (dl lane; `.part` + Range resume, cancel keeps the `.part`; 400 with a clear message if the disk is too small) |
| POST `/api/import/url` | `{url, kind:"checkpoint"\|"lora"\|"vae", name?}` | `{job_id}`. huggingface.co blob/resolve URLs, civitai.com model pages or api/download URLs (token from settings, 401/403 → "Civitai needs an API token, add it in Settings"), direct links. Only `.safetensors` (pickles refused) |
| POST `/api/import/file` | multipart `file`, form `kind` | `{ok, kind, name}`; refuses non-`.safetensors`, validates the safetensors header |
| POST `/api/generate/image` | `{prompt, negative, checkpoint, vae?, loras:[{name, weight}], width, height, steps, cfg, sampler, seed(-1=random), batch, clip_skip, pony?, init_image?(data URL), strength?}` | `{job_id}` |
| POST `/api/generate/video` | `{prompt, negative, model, width, height, frames, fps, steps, cfg, seed, init_image?}` | `{job_id}` |
| GET `/api/jobs/{id}` | | `{id, kind, state:"queued"\|"running"\|"done"\|"error"\|"cancelled", progress:0..1, step, total, message, results:[{url, thumb, meta}], error?}` |
| POST `/api/jobs/{id}/cancel` | | `{ok}` |
| GET `/api/events` | | Server-Sent Events: `data: <job json>` on every job change |
| GET `/api/gallery` | `?kind=image\|video&offset&limit` | `{items:[{id, kind, url, thumb, meta, created}], total}` newest first |
| DELETE `/api/gallery/{id}` | | `{ok}` |
| POST `/api/translate` | `{text, mode:"rules"\|"llm", source:"anime"\|"cartoon"\|"furry"\|"pony"\|"realistic", rating:"safe"\|"questionable"\|"explicit"}` | `{prompt, negative, tags, dropped, note?}` |
| GET `/api/datasets` | | `[{name, images:int, captioned:int}]` |
| POST `/api/datasets` | `{name}` | dataset |
| POST `/api/datasets/{name}/upload` | multipart `files[]` | `{added}` |
| GET `/api/datasets/{name}` | | `{name, trigger, items:[{file, url, caption}]}` |
| PUT `/api/datasets/{name}/caption` | `{file, caption}` | `{ok}` |
| DELETE `/api/datasets/{name}/item/{file}` | | `{ok}` |
| POST `/api/datasets/{name}/autocaption` | `{trigger?, threshold?, overwrite?}` | `{job_id}` |
| POST `/api/lora/quick` | `{name, type:"character"\|"style"\|"concept", base_checkpoint?}` (dataset of the same name must already hold images) | `{job_id}`: auto-caption (trigger = name, keeps existing captions) then train; message `tagging 12/30` then `training epoch 3/10 loss: 0.091`, progress covers both phases |
| POST `/api/train` | `{dataset, name, base_checkpoint, preset, trigger, overrides?:{dim, alpha, lr, epochs, repeats, resolution}}` | `{job_id}` |
| GET `/files/...` | | static files from data/outputs and data/datasets |

Job results urls point at `/files/outputs/...`. Training job `message` carries the latest
`epoch x/y loss 0.123`, `results` gets sample images as they appear and finally the LoRA.

## Web UI

Single page, Ultimit look. Copy the token blocks (`:root` + `[data-skin=…]` for mine, amber,
silver, verdant) and component styles (`.win`, corner-bracket `::before/::after` in accent,
`.wh .wt .wsub .wrule`, `.lbl` with the accent square, `.btn` with clipped corners, `.btn.pri`,
`.chip`, `.row/.sel`, `.tog` square toggles, selects/ranges, `#rail` + `.rb` rail buttons with the
accent bar on the active one, `#ticker` bottom bar) from Ultimit's mockup. Fonts: Michroma
(display), Chakra Petch (UI), Share Tech Mono (mono). Background: `--bg1` → `--bg2` with a light
canvas-drawn shard/hex pattern like the mockup's wallpaper (cheap, static, redrawn on resize).

- Left rail (84px): emblem (cat-ear bracket mark), then CREATE, MODELS, MOTION, LORA, TRANSLATE,
  GALLERY, SETTINGS; version vertical at the bottom.
- Bottom ticker: accent "NEKO" key + live status text (GPU name, VRAM, queue, current job %).
- Top-right status block in mono: time, GPU, job state.
- Each section is one big glass `.win` filling the area, title in Michroma, mono sub-caption.
- CREATE: left column = checkpoint select (Pony chip if pony), LoRA picker (add rows: select +
  weight slider -2..2, remove), prompt textarea, negative textarea (with a "NEG PRESETS" menu:
  Pony default, anime, realistic), a "→ PONY" button that sends the prompt through translate and
  replaces it (undo available), size presets (1024², 832×1216, 1216×832, 896×1152, 1152×896,
  custom), steps, CFG, sampler, seed (dice = -1, recycle = last), batch 1–4, clip skip, VAE,
  img2img drop zone + strength. Right column = big preview with progress bar (accent fill,
  mono %), thumbnails strip of the current batch, buttons: SAVE AS (download), REUSE PARAMS,
  TO MOTION (send image as I2V init), SEND TO DATASET. Ctrl+Enter = generate. Esc = cancel.
- MOTION: model select, prompt + negative, size (832×480, 480×832, 640×640), frames (33/49/81),
  fps, steps, cfg, seed, optional init image; preview `<video>` loop.
- MODELS: cards per catalog entry grouped Checkpoints / Video / Extras (label, family chip, RECOMMENDED chip,
  size, one-line note, then DOWNLOAD, or a progress bar "1.2 / 6.5 GB" + CANCEL, or an INSTALLED chip), free disk
  space chip, and an IMPORT panel: paste-a-link box + kind select + IMPORT, and a `.safetensors` drop zone.
  Downloads run in the background; when one finishes `/api/models` is refreshed so selects update without reload.
  CREATE and MOTION show a big "No model yet" card with the recommended entry's DOWNLOAD button (and SEE ALL
  MODELS) while nothing usable is installed.
- LORA: one screen. LoRA name (also the trigger word, shown), a type picker (CHARACTER / STYLE / OUTFIT-THING,
  mapped to presets character/style/concept), a base model select (default: the Pony checkpoint), a big image drop
  zone with thumbnails and a count (warns under 10, suggests 15-40) and one TRAIN button (`/api/lora/quick`). Live
  phase message and progress; when done a toast and TRY IT, which jumps to CREATE with the LoRA at 0.8 and the
  trigger word in the prompt. A small EDIT TAGS / ADVANCED toggle reveals the old 3-step wizard (01 DATASET · 02
  CAPTIONS · 03 TRAIN: caption editor, bulk tags, preset cards, dim/alpha/lr/epochs/repeats, loss sparkline).
  If `train_ready` is false show the exact setup command to run. Below: an IMPORT LORA strip (drop `.safetensors`
  or paste a link, `kind=lora`) and the list of installed LoRAs with DELETE.
- TRANSLATE: two panes. Left: prose input (placeholder an example GPT prompt), mode toggle
  RULES / LLM, source select, rating select. Right: resulting prompt + negative (editable),
  tag chips (click to remove), dropped words in dim mono, COPY and USE IN CREATE buttons.
- GALLERY: grid of images/videos, filter tabs IMAGES / VIDEOS, click → detail flyout with full
  meta, REUSE, DELETE, DOWNLOAD.
- SETTINGS: skin (4 swatches) + accent presets (Ultimit's 8: Pink #ff3d7f, Vermilion #ff5a36,
  Gold #ffc23d, Acid #c6ff3d, Mint #3dffb0, Cyan #3dd8ff, Blue #4d7cff, Violet #a66bff) + custom,
  motion on/off; paths (read-only display), LLM endpoint (base url, model, key), Civitai API token, VRAM mode
  (auto/low/high), default negative prompt, "open data folder" hint.
- Live updates via EventSource `/api/events`, falling back to polling `/api/jobs/{id}`.
- Skin/accent stored in localStorage and in settings.
- Accent override follows Ultimit's rule: on-accent text dark if luminance > 0.18 else white.
- No external JS libs.

## Setup scripts

- `setup.sh` (Ubuntu 22.04+): check `nvidia-smi`; ensure `git`, `ffmpeg`
  (apt via `sudo` only if missing, print the command if not allowed); install `uv` to
  ~/.local/bin if missing; `uv venv --python 3.12 .venv`; install torch/torchvision from
  `https://download.pytorch.org/whl/cu128`, then `requirements.txt`. Unless `--no-train`: clone
  kohya-ss/sd-scripts (branch `main`) into vendor/, `uv venv --python 3.10 .venv-train`, torch
  cu128 + its requirements + bitsandbytes. Write `~/.local/share/applications/nekostudio.desktop`
  (Exec `run.sh --open`). Idempotent; re-running updates.
- `setup.ps1` (Windows 10/11): same steps with winget fallback hints for git/ffmpeg, uv via the
  official PowerShell installer, `.venv\Scripts\python.exe`, Start Menu shortcut.
- `run.sh` / `run.ps1`: activate venv, `python -m nekostudio --open` (opens browser).
