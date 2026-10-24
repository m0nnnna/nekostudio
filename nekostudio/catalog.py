"""Ready-to-click model downloads. Every repo/file below was checked against the Hugging Face CDN."""
from __future__ import annotations

from . import config  # first: it points HF_HOME at the data dir before huggingface_hub reads it

from huggingface_hub import try_to_load_from_cache  # noqa: E402

# file=None means "snapshot the whole repo" (restricted by `only`/`skip` globs); `check` lists files
# that must exist in the HF cache for a snapshot to count as installed. `dest` renames a single file.
CATALOG: list[dict] = [
    dict(id="pony-v6", label="Pony Diffusion V6 XL", kind="checkpoint", family="pony",
         repo="LyliaEngine/Pony_Diffusion_V6_XL", file="ponyDiffusionV6XL_v6StartWithThisOne.safetensors",
         size_gb=6.94, note="The all-rounder for anime, cartoon and furry art; understands score_9 tags and booru tags.",
         recommended=True),
    dict(id="illustrious-v01", label="Illustrious XL v0.1", kind="checkpoint", family="illustrious",
         repo="OnomaAIResearch/Illustrious-xl-early-release-v0", file="Illustrious-XL-v0.1.safetensors",
         size_gb=6.94, note="Clean anime illustration with strong character knowledge; booru tags, no score tags.",
         recommended=False),
    dict(id="noobai-11", label="NoobAI-XL 1.1", kind="checkpoint", family="noobai",
         repo="Laxhar/noobai-XL-1.1", file="NoobAI-XL-v1.1.safetensors",
         size_gb=7.11, note="Illustrious-based anime model trained on Danbooru and e621; huge character and style range.",
         recommended=False),
    dict(id="animagine-4", label="Animagine XL 4.0", kind="checkpoint", family="animagine",
         repo="cagliostrolab/animagine-xl-4.0", file="animagine-xl-4.0.safetensors",
         size_gb=6.94, note="Polished anime look that follows prompts closely; great for characters and scenes.",
         recommended=False),
    dict(id="sdxl-base", label="SDXL base 1.0", kind="checkpoint", family="sdxl",
         repo="stabilityai/stable-diffusion-xl-base-1.0", file="sd_xl_base_1.0.safetensors",
         size_gb=6.94, note="The original SDXL: plain-English prompts, general purpose, good base for LoRAs.",
         recommended=False),
    dict(id="juggernaut-9", label="Juggernaut XL v9", kind="checkpoint", family="realistic",
         repo="RunDiffusion/Juggernaut-XL-v9", file="Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors",
         size_gb=7.11, note="Photorealistic people, places and products; write prompts in normal sentences.",
         recommended=False),
    dict(id="wan-t2v-1.3b", label="Wan 2.1 T2V 1.3B", kind="video", family="wan",
         repo="Wan-AI/Wan2.1-T2V-1.3B-Diffusers", file=None, size_gb=28.4,
         skip=["assets/*", "examples/*", "*.md"],
         check=["model_index.json", "vae/diffusion_pytorch_model.safetensors",
                "transformer/diffusion_pytorch_model-00002-of-00002.safetensors",
                "text_encoder/model-00005-of-00005.safetensors"],
         note="Text-to-video at 480p that fits a 12 GB card; the big download is the text encoder.",
         recommended=True),
    dict(id="sdxl-vae-fix", label="SDXL VAE fp16 fix", kind="vae", family="sdxl",
         repo="madebyollin/sdxl-vae-fp16-fix", file="sdxl_vae.safetensors", dest="sdxl-vae-fp16-fix.safetensors",
         size_gb=0.33, note="Fixes black or NaN images with SDXL in half precision; pick it as VAE in CREATE.",
         recommended=False),
    dict(id="wd-eva02-large", label="WD tagger EVA02 large v3", kind="tagger", family="sdxl",
         repo="SmilingWolf/wd-eva02-large-tagger-v3", file=None, size_gb=1.26,
         only=["model.onnx", "selected_tags.csv"], check=["model.onnx", "selected_tags.csv"],
         note="The best auto-captioner for LoRA datasets (used first by the LoRA screen).",
         recommended=True),
    dict(id="wd-vit", label="WD tagger ViT v3", kind="tagger", family="sdxl",
         repo="SmilingWolf/wd-vit-tagger-v3", file=None, size_gb=0.38,
         only=["model.onnx", "selected_tags.csv"], check=["model.onnx", "selected_tags.csv"],
         note="Smaller, faster auto-captioner; the fallback when the large one is missing.",
         recommended=False),
]
BY_ID = {e["id"]: e for e in CATALOG}
KIND_DIRS = {"checkpoint": config.CHECKPOINTS, "vae": config.VAES, "lora": config.LORAS}


def target(entry: dict):
    """Final path of a single-file entry."""
    return KIND_DIRS[entry["kind"]] / (entry.get("dest") or entry["file"].split("/")[-1])


def installed(entry: dict) -> bool:
    if entry["file"]:
        return target(entry).is_file()
    return all(isinstance(try_to_load_from_cache(entry["repo"], f), str) for f in entry["check"])


def public(entry: dict) -> dict:
    keys = ("id", "label", "kind", "family", "repo", "file", "size_gb", "note", "recommended")
    return {k: entry.get(k) for k in keys}


def video_installed(model_id: str) -> bool:
    """Is this video model fully in the HF cache? (catalog models check every shard)"""
    for e in CATALOG:
        if e["repo"] == model_id and e["kind"] == "video":
            return installed(e)
    return isinstance(try_to_load_from_cache(model_id, "model_index.json"), str)
