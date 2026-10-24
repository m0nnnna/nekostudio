# NekoStudio

A local AI art studio in one Python server and one browser UI: image generation (SDXL, Pony,
Illustrious, SD1.5), video generation (Wan 2.1), easy LoRA training, negative prompt presets and a
GPT-prose to Pony-tags translator. Runs on Ubuntu and Windows with an NVIDIA GPU (built for 12 GB
VRAM). MIT licence.

## Setup

Ubuntu 22.04+:

    ./setup.sh            # add --no-train to skip the LoRA trainer
    ./run.sh              # opens http://127.0.0.1:7860

Windows 10/11 (needs git and ffmpeg, e.g. `winget install Git.Git Gyan.FFmpeg`):

    setup.bat             # add -NoTrain via: powershell -File setup.ps1 -NoTrain
    run.bat

Setup creates `.venv` (Python 3.12, torch CUDA 12.8) via `uv`, and for training a separate
`.venv-train` with kohya sd-scripts in `vendor/`. Re-running setup updates everything. The server
itself starts without a GPU or models; `/api/status` shows what is missing.

### Running from a network share

NekoStudio can live on a Windows share (`\\server\share\nekostudio` or a mapped drive like `Z:`), and
Linux can run it from an SMB/NFS mount too. Run setup once on each PC that uses it. When the scripts see a
network path they keep the Python envs and the trainer on that PC's local disk
(`%LOCALAPPDATA%\NekoStudio\env-<id>` or `~/.local/share/nekostudio/env-<id>`), because loading
torch's DLLs over SMB is slow and every PC needs its own. Settings, models, datasets, LoRAs and outputs
stay on the share, so all PCs see the same studio.

- Start it with `run.bat` or the Start Menu shortcut. cmd.exe prints "UNC paths are not supported"
  when started in a `\\server` folder; that warning is harmless.
- If Windows asks "Do you want to run this file?" for files on the share, add the server to Local
  intranet (Internet Options > Security) or open it through a mapped drive.
- Keep the share path short, or turn on Windows long paths, because Hugging Face cache paths get long.
- If `models_dir` in `data/settings.json` points somewhere that doesn't exist on this PC (another OS's
  path, an unplugged drive), NekoStudio uses `data/models` instead and says so in the console.

## Getting started

1. Run the setup script (see Setup above) and start the app (`./run.sh` or `run.bat`).
2. Open http://127.0.0.1:7860 and go to MODELS.
3. Click DOWNLOAD on Pony Diffusion V6 XL (about 7 GB). You can keep working while it downloads.
4. Go to CREATE, type a prompt, press GENERATE.

## Models

MODELS has one-click downloads (Pony, Illustrious, NoobAI, Animagine, SDXL, a realistic model, the Wan video
model, a VAE and the auto-taggers). Downloads resume after a cancel or a crash. You can also import your own
`.safetensors` by dropping files or pasting a Hugging Face / Civitai link (Civitai usually needs an API token,
set it in SETTINGS). Pickle files (`.ckpt`, `.pt`) are refused.

Data lives in `./data` (override with env `NEKOSTUDIO_HOME`). Models can sit on another drive: set
`"models_dir"` in `data/settings.json` or env `NEKOSTUDIO_MODELS`.

- Checkpoints (`.safetensors`): `data/models/checkpoints/`
- LoRAs: `data/models/loras/` (trained LoRAs land here)
- VAEs: `data/models/vae/`

Video models are Hugging Face repos listed in settings, downloaded on first use to `data/hf/`.
Filenames containing "pony" turn on Pony mode (score tags, clip skip 2).

## Features

- CREATE: txt2img / img2img, LoRA stack with weights, samplers, seed, batch, clip skip, VAE.
- MOTION: Wan 2.1 text-to-video and image-to-video.
- MODELS: one-click model downloads and `.safetensors` import. LORA: one screen (name, type, pictures, TRAIN), LoRA import and delete.
- TRANSLATE: prose to Pony tags. GALLERY and SETTINGS (skins, accents, remote LLM endpoint, translator GPU layers).

## Pony translator

TRANSLATE turns GPT-style prose into real Pony/booru tags. Every tag is checked against the
Danbooru and e621 tag lists (with post counts and aliases), so no invented fragments get through.

- **Local** (best): a small instruct model (Qwen3 4B Instruct 2507, Q4_K_M, 2.5 GB) runs on the CPU through
  llama.cpp, so it never takes VRAM from image generation (SETTINGS has "GPU layers" if you want it on the
  GPU). Click DOWNLOAD TRANSLATOR on the TRANSLATE page (the model plus the two tag lists, about 2.5 GB,
  fetched one file at a time). It loads on first use and frees its memory after 10 idle minutes.
- **Rules**: offline fallback without a model; dictionary-based matching of phrases to tags.
- **Remote**: any OpenAI-compatible endpoint (OpenAI, OpenRouter, Ollama `http://127.0.0.1:11434/v1`, LM Studio),
  same prompt and the same tag checking.
- **Auto** (default, also used by the CREATE "to Pony" button): local if installed, else rules.

The result is ordered score tags, source, rating (always what you pick, default safe), character count,
then the rest, plus a suggested negative prompt, the tags it repaired (`from -> to`) and the words it dropped.
Check quality with `python tests/eval_translate.py --mode local` (or `rules`).

## Training a LoRA

1. LORA: type a name (it is also the trigger word), pick CHARACTER, STYLE or OUTFIT / THING, pick the base model
   and drop in 15 to 40 pictures.
2. Press TRAIN. It tags the pictures (WD14) and trains; progress and loss stream live.
3. Press TRY IT: CREATE opens with the LoRA at 0.8 and the trigger word in the prompt.

EDIT TAGS / ADVANCED opens the old wizard (caption editor, bulk tag edits, dim/alpha/lr/epochs/repeats).
