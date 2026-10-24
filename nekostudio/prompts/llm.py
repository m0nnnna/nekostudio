"""Shared LLM translator pieces (system prompt, few-shots, JSON schema, post-processing glue) plus the
optional external OpenAI-compatible endpoint. The local llama.cpp engine lives in local_llm.py and uses
exactly the same prompt, schema and tagdb post-processing."""
from __future__ import annotations

import json

import httpx

from . import postproc

SYSTEM = """You translate plain-English image descriptions into Danbooru/e621 style tags for Pony Diffusion XL.
Reply with JSON only: {"characters": [...], "tags": [...], "rating_hint": "..."}.

HOW PONY TAGS WORK
- Tags are short, lowercase, real booru tags written with spaces ("long hair", "looking at viewer").
- Every tag must be something a booru artist would plainly use: an object, a colour+object, a body feature, a pose, an action, a place, a lighting or weather condition, a camera angle. Never output a verb phrase, a sentence fragment or an adjective alone ("flowing", "dramatic", "cozy", "spills", "behind", "fluffy").
- Do not copy phrases from the text. Convert every idea into the standard tag for it.
- Put the subject first: the character count tag, then solo (if exactly one character), then subject features, clothing, pose/action, objects, setting, lighting, camera.
- Character count tags: 1girl, 1boy, 2girls, 2boys, 1girl 1boy written as "1girl, 1boy", 3girls, multiple girls (4+), and "no humans" when no person is present (animals, monsters, landscapes, objects). Use "solo" for exactly one character. A woman, girl, witch or mercenary woman is 1girl; a man, boy or male knight is 1boy ("his" means male). Never use 1girl or 1boy when the subject is only an animal or creature.
- Furry or anthropomorphic subjects: add anthro (or furry female / furry male) plus the species, e.g. "fox girl, fox ears, fox tail, furry female, anthro"; keep the 1girl/1boy count tag too.
- Split compound descriptions into separate tags: "flowing auburn hair" -> "long hair, brown hair"; "ornate silver plate armor" -> "armor, plate armor, silver armor"; "white bikini and sunglasses" -> "white bikini, sunglasses". Colours attach to one noun each: "green apron", "black cat".
- Hair: length tag + colour tag ("long hair", "pink hair", "twintails", "ponytail"). Eyes: colour + "eyes" ("green eyes"; amber -> "yellow eyes"; auburn/copper hair -> "brown hair").
- Map prose to the standard tag: leaping -> jumping, midair; low angle / worm's-eye -> from below; high angle / overhead -> from above; mist -> fog; glowing blue sword -> holding sword, glowing sword; reading a book -> reading, book; raining -> rain; a crackling fire -> fireplace or fire; sleepy -> sleeping or closed eyes; giggling -> laughing; neon signs -> neon lights; chrome arm -> mechanical arms; cafe -> cafe; dawn -> dawn; golden hour -> sunset or sunlight; by candlelight -> candlelight; sitting on the bed -> sitting, on bed; room lit only by a monitor -> dark, indoors; wind in hair -> wind.
- More mappings: chrome / metal / robotic arm -> mechanical arms; katana drawn, drawing a sword -> holding sword, katana; sailor uniform -> serafuku, school uniform; sharing an umbrella -> shared umbrella, umbrella; rainy -> rain; coffee, latte -> coffee, cup; lounging -> reclining; sunglasses pushed up on the head -> eyewear on head, sunglasses; oversized hoodie -> hoodie, oversized clothes; playing video games -> playing games, video game; late at night in a dark room -> night, dark; teenage / young -> nothing (no tag).
- With two or more characters, give each character's own features as separate tags (every hair length and colour, glasses, clothes), and do not add 1girl if the count tag is 2girls.
- Cover EVERYTHING concrete the text mentions: every object, furniture, clothing item, plant, animal, building part, hair and eye colour, expression, pose, weather, time of day and light source gets its own tag. Held or used objects also get "holding <object>" or "<object>" tags.
- Keep the exact noun the text uses when it is a real tag (armchair, spellbook, fireplace, katana) instead of generalising it (chair, book, sword).
- Mention the place and its type: indoors or outdoors, the time of day (night, sunset, dawn, day), weather (rain, snow, fog), and obvious props as separate tags.
- DROP: quality and style filler (masterpiece, best quality, highly detailed, 8k, 4k, cinematic, dramatic, epic, stunning, beautiful, cute, adorable, fluffy, cozy, photorealistic), instructions to the artist (create, draw, generate, illustration, image, shot), vague words, and anything you would have to invent. Score, source and rating tags are added by the tool: never output them.
- Do not add content that the text does not describe or clearly imply (no nudity or sexual content unless described).
- "characters" lists named fictional characters only (e.g. "hatsune miku"); otherwise []. "rating_hint" is "safe", "questionable" or "explicit" based on the text.
- 20 to 45 tags, most important first."""

FEWSHOT = [
    ("A muscular anthropomorphic tiger man in a tank top lifting a barbell in a crowded gym, sweat on his brow, harsh fluorescent lighting.",
     {"characters": [], "tags": ["1boy", "solo", "anthro", "tiger", "tiger boy", "furry male", "muscular male", "muscular", "tank top", "weightlifting",
                                 "barbell", "gym", "indoors", "sweat", "standing", "looking at viewer"],
      "rating_hint": "safe"}),
    ("A tired astronaut sitting on the edge of a crater, helmet resting in her lap, watching Earth rise over the horizon. Cinematic, ultra detailed, 4k.",
     {"characters": [], "tags": ["1girl", "solo", "astronaut", "spacesuit", "sitting", "holding helmet", "helmet", "tired", "crater",
                                 "planet", "earth", "horizon", "starry sky", "space", "from behind", "scenery", "outdoors"],
      "rating_hint": "safe"}),
    ("Two female detectives in trench coats examining a clue under a streetlight on a foggy night, one tall with short grey hair and a monocle, the other with long red braids, both frowning, 35mm film still.",
     {"characters": [], "tags": ["2girls", "detective", "trench coat", "streetlight", "fog", "night", "outdoors", "short hair", "grey hair", "monocle",
                                 "long hair", "red hair", "braid", "frown", "standing", "street", "multiple girls"],
      "rating_hint": "safe"}),
    ("Draw a little girl and her grandmother baking bread together in a rustic kitchen, flour on their aprons, warm morning light through the window.",
     {"characters": [], "tags": ["2girls", "child", "old woman", "baking", "bread", "kitchen", "indoors", "apron", "flour", "smile", "window",
                                 "sunlight", "morning", "grandmother and granddaughter", "multiple girls"],
      "rating_hint": "safe"}),
    ("A lonely lighthouse on a jagged cliff during a violent thunderstorm, waves crashing against the rocks, lightning splitting the dark sky.",
     {"characters": [], "tags": ["no humans", "lighthouse", "cliff", "storm", "lightning", "waves", "rock", "ocean", "night", "dark",
                                 "cloudy sky", "rain", "scenery", "outdoors"],
      "rating_hint": "safe"}),
    ("A samurai leaping through the air, katana slashing at a charging oni, seen from a worm's-eye view, dust swirling around him, dramatic sunset sky.",
     {"characters": [], "tags": ["1boy", "solo", "samurai", "japanese clothes", "jumping", "midair", "holding sword", "katana", "oni", "fighting",
                                 "action", "from below", "dust", "sunset", "orange sky", "outdoors"],
      "rating_hint": "safe"}),
]

SCHEMA = {
    "type": "object",
    "properties": {
        "characters": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "tags": {"type": "array", "items": {"type": "string", "maxLength": 40}, "minItems": 3, "maxItems": 48},
        "rating_hint": {"type": "string", "enum": ["safe", "questionable", "explicit"]},
    },
    "required": ["characters", "tags", "rating_hint"],
}


def messages(text: str) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM}]
    for u, a in FEWSHOT:
        msgs.append({"role": "user", "content": u})
        msgs.append({"role": "assistant", "content": json.dumps(a, ensure_ascii=False)})
    msgs.append({"role": "user", "content": text.strip()})
    return msgs


def parse(content: str) -> dict:
    """JSON from the model; tolerate code fences and plain comma lists from weaker endpoints."""
    c = content.strip()
    if c.startswith("```"):
        c = c.strip("`")
        c = c[c.find("\n") + 1:] if "\n" in c else c
    try:
        data = json.loads(c[c.find("{"):c.rfind("}") + 1])
        if isinstance(data, dict) and isinstance(data.get("tags"), list):
            return data
    except ValueError:
        pass
    return {"tags": [t for t in c.replace("\n", ",").split(",") if t.strip()], "characters": [], "rating_hint": "safe"}


def translate_remote(text: str, source: str, rating: str, cfg: dict) -> dict:
    base = (cfg.get("base_url") or "").rstrip("/")
    model = cfg.get("model") or ""
    if not base or not model:
        raise ValueError("LLM base URL and model are not configured (Settings).")
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    body = {"model": model, "temperature": 0.2, "messages": messages(text),
            "response_format": {"type": "json_schema", "json_schema": {"name": "pony_tags", "schema": SCHEMA}}}
    r = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=180)
    if r.status_code == 400:      # endpoint without json_schema support: retry as a plain request
        body.pop("response_format")
        r = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=180)
    r.raise_for_status()
    data = parse(r.json()["choices"][0]["message"]["content"])
    res = postproc.finish(data, text, source, rating)
    res["engine"] = "remote"
    return res
