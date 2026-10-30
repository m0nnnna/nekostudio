"""OUTFITS: put the character from a reference picture into the outfit from a second picture.

The recipe is fixed; the user only adds a prompt, a negative and the usual sampling settings:
1. The WD tagger reads both pictures. From the character we keep only what makes them recognisable (hair, eyes,
   ears, tail, skin, markings, hair accessories); from the outfit only clothing and accessories. Sheet and
   mannequin tags (reference sheet, multiple views, color palette, faceless, no humans ...) are dropped.
2. Prompt = user prompt + "solo" + character tags + outfit tags. The negative gets the sheet/mannequin tags.
3. SDXL txt2img with two IP-Adapters: plus-face on the character (the user's face box, else the whole picture)
   and plus on the outfit picture, so details the tags can't name still come through.
"""
from __future__ import annotations

import gc
import random
import re

from ..jobs import Job
from . import image as image_engine

# Tags that describe the character rather than what they wear. Hair accessories count as part of the
# character design (the X hairclips on a reference sheet belong to the character, not to the new outfit).
IDENTITY = re.compile(
    r"\b(1girl|1boy|1other|female|male|androgynous|hair|bangs|ahoge|sidelocks|ponytail|twintails|braids?|"
    r"hair bun|hairclip|hairband|hair ornament|eyes|pupils|eyelashes|eyebrows|heterochromia|ears|ear fluff|"
    r"tail|horns?|wings|halo|fangs?|skin|freckles|mole|scar|whiskers|facial mark|markings|tanlines|"
    r"pointy ears|elf|kemonomimi mode|furry|anthro|breasts|flat chest|muscular|ear piercing)\b")
CLOTHING = re.compile(
    r"\b(shirt|t-shirt|blouse|dress|skirt|shorts|pants|jeans|trousers|leggings|jacket|coat|hoodie|sweater|"
    r"cardigan|vest|top|crop top|tank top|camisole|bra|underwear|panties|bikini|swimsuit|leotard|bodysuit|"
    r"uniform|serafuku|kimono|yukata|hakama|armor|robe|cape|cloak|apron|corset|thighhighs|kneehighs|socks|"
    r"stockings|pantyhose|legwear|garter straps?|thigh strap|boots|shoes|sneakers|high heels|sandals|loafers|"
    r"footwear|gloves|mittens|sleeves|sleeveless|collar|choker|necktie|bowtie|tie|scarf|belt|buckle|straps?|"
    r"harness|suspenders|hat|cap|beret|hood|headwear|beanie|crown|tiara|earrings|necklace|pendant|jewelry|"
    r"bracelet|ring|chain|zipper|pocket|buttons|lace|frills|ribbon|bow|off shoulder|bare shoulders|midriff|"
    r"clothes|clothing|outfit|print|striped|plaid|glasses|eyewear|goggles|bag|backpack|wristband|armband|"
    r"cuffs|pouch|o-ring|studded|spiked|fishnets|mask|headphones|wrist cuffs|neckerchief|sailor collar|"
    r"overalls|tabard|sash|obi|bandages|bandaid|tassel|fur trim|fur-trimmed)\b")
# Sheet layout, mannequin and empty-background tags: never wanted in the result.
LAYOUT = re.compile(
    r"\b(reference sheet|character sheet|model sheet|multiple views|color palette|palette|turnaround|"
    r"from behind|back|close-up|zoom layer|inset|split screen|chibi|chibi inset|text|english text|"
    r"character name|artist name|signature|watermark|simple background|white background|grey background|"
    r"multiple girls|multiple boys|no humans|faceless|faceless female|faceless male|headless|mannequin|"
    r"out of frame|head out of frame|cropped|lower body|upper body|still life|object focus|clothes focus|"
    r"solo focus|solo|border|outside border|collage)\b")

EXTRA_NEG = ("multiple views, reference sheet, character sheet, color palette, split screen, collage, text, "
             "faceless, headless, mannequin, no humans, nude")
CHAR_MAX, OUTFIT_MAX = 14, 18   # SDXL reads 77 CLIP tokens; the adapters carry what the tags leave out


def character_tags(tags: list[tuple[str, float]]) -> list[str]:
    return [t for t, _ in tags if IDENTITY.search(t) and not LAYOUT.fullmatch(t)][:CHAR_MAX]


def outfit_tags(tags: list[tuple[str, float]]) -> list[str]:
    return [t for t, _ in tags if CLOTHING.search(t) and not IDENTITY.search(t) and not LAYOUT.fullmatch(t)][:OUTFIT_MAX]


def build_prompt(user: str, char: list[str], outfit: list[str]) -> str:
    seen, out = set(), []
    for part in [user.strip(" ,"), "solo", *char, *outfit]:
        for t in (x.strip() for x in part.split(",")):
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
    return ", ".join(out)


def _square(img, box=None):
    """Optional crop to box (fractions x0,y0,x1,y1), then pad to a white square: CLIP center-crops otherwise."""
    from PIL import Image
    if box:
        x0, y0, x1, y1 = (max(0.0, min(1.0, float(v))) for v in box)
        if x1 - x0 > 0.02 and y1 - y0 > 0.02:
            w, h = img.size
            # a little room around the face helps the face adapter
            mx, my = (x1 - x0) * 0.15, (y1 - y0) * 0.15
            img = img.crop((int(max(0, x0 - mx) * w), int(max(0, y0 - my) * h),
                            int(min(1, x1 + mx) * w), int(min(1, y1 + my) * h)))
    side = max(img.size)
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return canvas


def _read_tags(job: Job, char_img, outfit_img) -> tuple[list[str], list[str]]:
    from ..lora import dataset as ds
    # CPU: two pictures are quick, and the tagger never competes with a checkpoint already in VRAM
    sess, rows = ds._load_tagger(job, cpu=True)
    job.update(message="reading the character ...")
    char = character_tags(ds.tag_image(sess, rows, char_img))
    job.check()
    job.update(message="reading the outfit ...")
    outfit = outfit_tags(ds.tag_image(sess, rows, outfit_img))
    del sess
    gc.collect()
    return char, outfit


def run(job: Job, p: dict):
    import torch

    if not p.get("character") or not p.get("outfit"):
        raise RuntimeError("OUTFITS needs a character picture and an outfit picture.")
    ckpt = p.get("checkpoint") or ""
    if not ckpt:
        raise RuntimeError("No checkpoint selected. Download one in MODELS.")
    from .. import catalog
    if catalog.ip_adapter_dir() is None:
        raise RuntimeError("OUTFITS needs the IP-Adapter: download it in MODELS.")
    char_img = image_engine.decode_data_url(p["character"])
    outfit_img = image_engine.decode_data_url(p["outfit"])

    char, outfit = _read_tags(job, char_img, outfit_img)
    job.check()
    user_neg = (p.get("negative") or "").strip(" ,")
    prompt, negative, pony = image_engine.apply_pony(build_prompt(p.get("prompt", ""), char, outfit),
                                                     f"{user_neg}, {EXTRA_NEG}" if user_neg else EXTRA_NEG,
                                                     ckpt, p.get("pony"))
    clip_skip = p.get("clip_skip") or (2 if pony else 1)

    steps = int(p.get("steps") or 28)
    width, height = int(p.get("width") or 832) // 8 * 8, int(p.get("height") or 1216) // 8 * 8
    batch = max(1, min(4, int(p.get("batch") or 1)))
    seed = int(p.get("seed", -1))
    if seed < 0:
        seed = random.randint(0, 2**32 - 1)

    pipe = image_engine._load_pipe(job, ckpt, p.get("vae") or image_engine._auto_vae(ckpt))
    if image_engine._state["kind"] != "sdxl":
        raise RuntimeError("OUTFITS needs an SDXL-family checkpoint (Pony, Illustrious, NoobAI, SDXL ...).")
    job.check()
    image_engine._set_sampler(pipe, p.get("sampler") or "euler_a")
    image_engine._apply_loras(pipe, p.get("loras") or [])
    image_engine.set_ip_adapters(job, pipe, True)
    char_s, outfit_s = float(p.get("character_strength") or 0.5), float(p.get("outfit_strength") or 0.6)
    pipe.set_ip_adapter_scale([char_s, outfit_s])

    def cb(_pipe, i, _t, kw):
        job.check()
        total = getattr(_pipe, "num_timesteps", steps) or steps
        job.update(progress=(i + 1) / total, step=i + 1, total=total, message=f"step {i + 1}/{total}")
        return kw

    kwargs = dict(prompt=prompt, negative_prompt=negative, num_inference_steps=steps, width=width, height=height,
                  guidance_scale=float(p.get("cfg") or 6.0), num_images_per_prompt=batch,
                  ip_adapter_image=[_square(char_img, p.get("face_box")), _square(outfit_img)],
                  generator=[torch.Generator("cpu").manual_seed(seed + i) for i in range(batch)],
                  callback_on_step_end=cb)
    if int(clip_skip) - 2 > 0:   # SDXL already uses the penultimate CLIP layer (see image.run)
        kwargs["clip_skip"] = int(clip_skip) - 2

    job.update(message="generating...", step=0, total=steps, progress=0)
    try:
        images = pipe(**kwargs).images
    except BaseException:
        image_engine.unload()
        raise
    image_engine._save(job, images, {**p, "batch": batch},
                       dict(prompt=prompt, negative=negative, seed=seed, pony=pony, clip_skip=int(clip_skip),
                            width=width, height=height, mode="outfit", character_tags=char, outfit_tags=outfit,
                            character_strength=char_s, outfit_strength=outfit_s))
