"""Shared tag post-processing for every translation engine: validate against tagdb, fix, drop, order.

Order: score tags, source, rating, count tags (+solo), character/copyright, everything else; deduped.
The rating tag always comes from the user's choice, never from the model.
"""
from __future__ import annotations

import re

from . import tagdb

SCORE_TAGS = ["score_9", "score_8_up", "score_7_up"]
SOURCE_TAGS = {"anime": "source_anime", "cartoon": "source_cartoon", "furry": "source_furry",
               "pony": "source_pony", "realistic": None}
RATINGS = {"safe": "rating_safe", "questionable": "rating_questionable", "explicit": "rating_explicit"}

COUNT_RE = re.compile(r"^(\d+)(girl|boy|other)s?$")
COUNT_WORDS = {"multiple girls", "multiple boys", "no humans", "multiple others"}

# quality / filler / instructions that must never become tags (score tags already cover quality)
QUALITY = {"masterpiece", "best quality", "high quality", "highly detailed", "ultra detailed", "very detailed", "detailed",
           "8k", "4k", "2k", "hd", "uhd", "hdr", "cinematic", "cinematic lighting", "dramatic", "dramatic lighting", "epic", "stunning",
           "beautiful", "cute", "adorable", "photorealistic", "realistic", "illustration", "image", "artwork", "digital art",
           "award winning", "trending on artstation", "sharp focus", "intricate", "intricate details", "ultra realistic",
           "professional", "amazing", "gorgeous", "lovely", "fluffy", "cozy", "warm", "soft", "dynamic", "atmospheric", "moody"}
PERSON_WORDS = {"woman", "man", "girl", "boy", "lady", "guy", "women", "men", "girls", "boys", "female", "male", "teenage", "adolescent",
                "person", "people", "human"}
VAGUE = {"expressions", "expression", "on head", "curled", "nostril", "nostrils", "hair", "eyes", "face", "body", "light", "lighting", "color", "colors", "colour", "style", "background", "detail",
         "details", "shot", "view", "scene", "thing", "stuff", "flowing", "behind", "above", "below", "across", "around",
         "far", "off", "only", "late", "both", "other", "one", "pose", "posing"}
KEEP_META = {"sketch", "greyscale", "monochrome", "comic", "traditional media", "pixel art", "lineart", "signature",
             "limited palette", "partially colored", "spot color", "photo", "cropped", "text", "chibi"}
NSFW = {"nsfw", "nude", "completely nude", "topless", "bottomless", "nipples", "pussy", "penis", "sex", "vaginal", "anal", "cum",
        "cleavage cutout", "explicit", "areolae", "spread legs", "fellatio", "erection", "naked"}
SAFE_REMOVE = NSFW | {"underwear", "panties", "bra", "lingerie"}

_WORD = re.compile(r"[a-z0-9']+")

# ---------------------------------------------------------------------------------------------
# character count inference from the prose
# ---------------------------------------------------------------------------------------------
FEMALE = {"girl", "woman", "lady", "witch", "maiden", "princess", "queen", "schoolgirl", "mother", "sister", "daughter", "heroine",
          "sorceress", "priestess", "nun", "maid", "waitress", "actress", "goddess", "female", "mom", "grandmother", "grandma",
          "aunt", "wife", "girlfriend", "bride", "empress", "duchess", "countess", "huntress", "seamstress", "miko", "idol", "women",
          "girls", "ladies", "daughters", "sisters", "mothers", "witches", "maids", "nurse"}
MALE = {"boy", "man", "guy", "gentleman", "prince", "king", "father", "brother", "son", "hero", "male", "dad", "grandfather",
        "grandpa", "uncle", "husband", "boyfriend", "groom", "emperor", "duke", "count", "boys", "men", "guys", "fathers",
        "brothers", "sons", "kings", "princes", "gentlemen", "monk", "butler"}
NEUTRAL_PERSON = {"person", "people", "character", "warrior", "knight", "mercenary", "wizard", "mage", "adventurer", "figure",
                  "silhouette", "traveler", "traveller", "samurai", "ninja", "soldier", "pirate", "elf", "dwarf", "student",
                  "teacher", "barista", "chef", "doctor", "scientist", "astronaut", "robot", "android", "cyborg", "child", "kid",
                  "teenager", "teen", "human", "someone", "rogue", "archer", "assassin", "sorcerer", "thief", "paladin",
                  "cowboy", "detective", "musician", "dancer", "singer", "girlfriend", "couple", "friends", "twins"}
ANIMALS = {"cat", "dog", "wolf", "fox", "dragon", "bird", "horse", "rabbit", "bunny", "lion", "tiger", "bear", "owl", "fish",
           "snake", "turtle", "frog", "deer", "squirrel", "mouse", "fox", "kitten", "puppy", "creature", "monster", "cow",
           "pig", "sheep", "whale", "shark", "butterfly", "bee", "spider", "phoenix", "unicorn", "slime", "ghost", "wyvern"}
NUMBERS = {"one": 1, "a": 1, "an": 1, "1": 1, "two": 2, "2": 2, "pair": 2, "three": 3, "3": 3, "four": 4, "4": 4, "five": 5, "5": 5,
           "six": 6, "6": 6, "several": 6, "many": 6, "group": 6, "bunch": 6}
FEM_PRON = {"she", "her", "hers", "herself"}
MALE_PRON = {"he", "him", "his", "himself"}
_PLURAL_F = {"girls", "women", "ladies", "daughters", "sisters", "mothers", "witches", "maids"}
_PLURAL_M = {"boys", "men", "guys", "fathers", "brothers", "sons", "kings", "princes", "gentlemen"}
_ADJ_GAP = 4


def infer_count(text: str) -> list[str]:
    """Count tags implied by the prose, e.g. ['1girl'], ['2girls','1boy'], ['no humans'] or [] when unknown."""
    toks = _WORD.findall(text.lower().replace("'s", ""))
    f = m = 0
    f_pl = m_pl = False
    i = 0
    while i < len(toks):
        w = toks[i]
        fem, male = w in FEMALE, w in MALE
        if fem or male:
            prev = toks[max(0, i - _ADJ_GAP):i]
            if "the" in prev[-2:] or "same" in prev[-2:]:
                i += 1
                continue
            n = 1
            # "two ... girls" / "a pair of girls": nearest number word looking back
            for p in reversed(prev):
                if p in NUMBERS and p not in ("a", "an"):
                    n = NUMBERS[p]
                    break
                if p in ("a", "an", "one"):
                    n = 1
                    break
            plural = w in _PLURAL_F or w in _PLURAL_M or w in ("women", "men", "ladies", "witches")
            if plural and not any(p in NUMBERS for p in prev):
                n = 4  # bare plural ("girls") -> multiple girls
            if fem:
                f += n
                f_pl |= n >= 4
            else:
                m += n
                m_pl |= n >= 4
        i += 1
    if f == 0 and m == 0:
        fp = any(t in FEM_PRON for t in toks)
        mp = any(t in MALE_PRON for t in toks)
        generic = any(t in NEUTRAL_PERSON for t in toks)
        if fp and not mp:
            f = 1
        elif mp and not fp:
            m = 1
        elif fp and mp:
            f = m = 1
        elif not generic:
            return ["no humans"]
        else:
            return []
    out = []
    for n, g in ((f, "girl"), (m, "boy")):
        if n == 0:
            continue
        out.append(f"multiple {g}s" if n >= 4 else f"{n}{g}" if n == 1 else f"{n}{g}s")
    return out



HOLD_WEAPONS = {"sword": "sword", "katana": "sword", "dagger": "dagger", "spear": "spear", "staff": "staff", "axe": "axe",
                "gun": "gun", "rifle": "rifle", "pistol": "handgun", "wand": "wand"}
HOLD_VERBS = {"holding", "wielding", "gripping", "brandishing", "carrying", "drawn", "draws", "drawing", "unsheathed", "unsheathing",
              "swinging", "clutching", "raising", "slashing", "wields", "holds"}
COLOURS_BARE = {"oversized", "arched", "wooden", "glowing", "plate", "leather", "potion", "black", "white", "red", "blue", "green", "yellow", "pink", "purple", "orange", "brown", "grey", "silver", "gold",
                "blonde", "aqua", "golden"}
NO_BARE = {"hair", "eyes", "fur", "skin", "background", "sky", "theme", "clothes", "clothing", "gradient", "tail", "ears", "wings", "dress shirt"}
INDOORS = {"armchair", "fireplace", "bed", "bedroom", "kitchen", "cafe", "couch", "sofa", "bookshelf", "library", "bar", "desk",
            "table", "counter", "cafe", "classroom", "indoors", "curtains", "ceiling", "floor", "chair", "lamp", "window", "potion", "shelf",
            "monitor", "computer", "gym", "restaurant", "bathroom", "stairs", "throne room", "laboratory", "workshop", "inside"}
OUTDOORS = {"street", "forest", "rooftop", "beach", "city", "mountain", "ocean", "sky", "field", "garden", "park", "outdoors",
             "river", "lake", "snow", "pool", "road", "bridge", "cliff", "meadow", "desert", "cityscape", "sunset", "night sky",
             "waterfall", "village", "town", "path", "hill", "tree", "grass", "flower field", "sea", "island"}
ANIMAL_PARTS = ("fox", "wolf", "cat", "dog", "rabbit", "bunny", "tiger", "lion", "bear", "horse", "deer", "cow", "sheep", "mouse",
                 "raccoon", "dragon", "demon", "bird")


def enrich(tags: list[str], text: str, rating: str = "safe") -> list[str]:
    """Add tags that a booru annotator would add and prose leaves implicit (indoors/outdoors, bare nouns, furry species parts)."""
    tags = list(tags)
    low = text.lower()
    furry = re.search(r"anthro|furry|\b(?:%s) (?:girl|boy|man|woman)\b|catgirl|fursona" % "|".join(ANIMAL_PARTS), low)
    if not furry:
        # e621's bare "female"/"male" are noise on anime prompts; the count tags already say it
        tags = [t for t in tags if t not in ("furry female", "furry male", "furry", "anthro", "female", "male")]
    have = set(tags)
    toks = low.replace("-", " ").split()
    for i, w in enumerate(toks):      # weapon next to a holding verb => "holding sword"
        w = w.strip(",.;:")
        if w in HOLD_WEAPONS and any(x.strip(",.;:") in HOLD_VERBS for x in toks[max(0, i - 4):i + 5]):
            for t in (["holding " + HOLD_WEAPONS[w]] + (["katana"] if w == "katana" else [])):
                if t not in have and tagdb.is_tag(t):
                    tags.append(t)
                    have.add(t)
    for t in list(tags):
        parts = t.split(" ")
        # "green apron" -> also "apron"; "arched window" -> "window"
        if len(parts) == 2 and (parts[0] in COLOURS_BARE or t.endswith(" window")) and parts[1] not in NO_BARE:
            n = parts[1]
            if n not in have and tagdb.count(n) >= 1000 and n not in VAGUE and tagdb.category(n) == "general":
                tags.append(n)
                have.add(n)
    for t in list(tags):
        for extra in IMPLY.get(t, ()):
            if extra not in have and tagdb.is_tag(extra):
                tags.append(extra)
                have.add(extra)
    if have & INDOORS and have & OUTDOORS and "indoors" in have and "outdoors" in have:
        # a model that says both: keep the one the scene tags support
        out_only = have & OUTDOORS - {"outdoors"}
        in_only = have & INDOORS - {"indoors"}
        tags = [t for t in tags if t != ("indoors" if len(out_only) > len(in_only) else "outdoors")]
        have = set(tags)
    if "elf" in have and "pointy ears" not in have:
        tags.append("pointy ears")
    if not have & {"indoors", "outdoors"}:
        if have & INDOORS:
            tags.append("indoors")
        elif have & OUTDOORS:
            tags.append("outdoors")
    male = any(is_count(t) and "boy" in t for t in tags)
    female = any(is_count(t) and "girl" in t for t in tags)
    for a in ANIMAL_PARTS:     # "fox girl" -> fox ears, fox tail
        for g in ("girl", "boy"):
            if f"{a} {g}" in have or re.search(rf"\b{a} {g}s?\b", low):
                for part in (g, "ears", "tail"):
                    c = tagdb.lookup(f"{a} {part}")  # via aliases: "bunny ears" -> "rabbit ears"
                    if c and c not in have:
                        tags.append(c)
                        have.add(c)
    if re.search(r"\b(anthro|anthropomorphic|furry|fursona)\b", low):
        for flag, tag in ((female, "furry female"), (male, "furry male")):
            if flag and tag not in have and tagdb.is_tag(tag):
                tags.append(tag)
    return tags


# ---------------------------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------------------------

def _dedupe(tags):
    seen, out = set(), []
    for t in tags:
        k = t.lower()
        if t and k not in seen:
            seen.add(k)
            out.append(t)
    return out


def is_count(t: str) -> bool:
    return bool(COUNT_RE.match(t)) or t in COUNT_WORDS


def assemble(tags: list[str], source: str = "anime", rating: str = "safe") -> list[str]:
    """score, source, rating, count tags (+solo), character/copyright, then the rest."""
    tags = [t.strip() for t in tags if t and t.strip()]
    body = [t for t in tags if not t.startswith(("score_", "source_", "rating_"))]
    counts = [t for t in body if is_count(t)]
    if counts:  # e621 aliases map "bunny girl" etc. to bare "female"; 1girl already says it
        body = [t for t in body if t not in ("female", "male")]
    # contradictions: "no humans" + people; 1girl next to 2girls...
    people = [c for c in counts if c != "no humans"]
    if people:
        counts = people
    for g in ("girl", "boy"):
        if any(c in (f"2{g}s", f"3{g}s", f"multiple {g}s") or re.match(rf"^[2-9]{g}s$", c) for c in counts):
            counts = [c for c in counts if c != f"1{g}"]
    counts.sort(key=lambda c: (0 if "girl" in c else 1 if "boy" in c else 2))
    n_people = 0
    for c in counts:
        m = COUNT_RE.match(c)
        n_people += int(m.group(1)) if m else 4
    has_solo = "solo" in body
    solo = n_people == 1 or (has_solo and n_people == 0 and "no humans" not in counts)
    named = [t for t in body if not is_count(t) and t != "solo" and tagdb.category(t) in ("character", "copyright")]
    rest = [t for t in body if not is_count(t) and t != "solo" and t not in named]
    head = list(SCORE_TAGS)
    if SOURCE_TAGS.get(source):
        head.append(SOURCE_TAGS[source])
    head.append(RATINGS.get(rating, "rating_safe"))
    return _dedupe(head + counts + (["solo"] if solo else []) + named + rest)


def suggest_negative(source: str = "anime", rating: str = "safe", tags: list[str] | None = None) -> str:
    neg = ["score_6", "score_5", "score_4", "worst quality", "low quality", "bad anatomy", "bad hands",
           "missing fingers", "extra digits", "fewer digits", "cropped", "watermark", "text", "signature",
           "jpeg artifacts", "blurry"]
    if source == "realistic":
        neg += ["anime", "cartoon", "3d", "drawing"]
    else:
        neg += ["realistic", "photo"]
    if rating == "safe":
        neg += ["nsfw", "explicit"]
    elif rating == "questionable":
        neg += ["explicit"]
    return ", ".join(neg)


IMPLY = {"sailor uniform": ["serafuku", "school uniform"], "serafuku": ["school uniform"], "cityscape": ["city"],
         "lounging": ["reclining"], "mechanical arm": ["mechanical arms"], "oversized hoodie": ["oversized clothes"],
         "oversized sweater": ["oversized clothes"], "oversized shirt": ["oversized clothes"]}
COLOUR_SYN = {"auburn": "brown", "chestnut": "brown", "copper": "orange", "ginger": "orange", "russet": "brown", "hazel": "brown",
              "chocolate": "brown", "raven": "black", "ebony": "black", "jet": "black", "crimson": "red", "scarlet": "red",
              "ruby": "red", "violet": "purple", "lavender": "purple", "lilac": "purple", "magenta": "pink", "navy": "blue",
              "azure": "blue", "cyan": "aqua", "turquoise": "aqua", "teal": "aqua", "emerald": "green", "golden": "blonde",
              "gold": "blonde", "platinum": "blonde", "blond": "blonde", "yellow": "blonde", "amber": "yellow", "gray": "grey",
              "silver": "silver", "white": "white", "snow": "white", "ivory": "white", "cream": "white", "sapphire": "blue",
              "rose": "pink", "peach": "orange", "burgundy": "red", "maroon": "red", "indigo": "purple"}

FIX = {"flowing hair": "long hair", "mechanical arm": "mechanical arms", "indoor": "indoors", "outdoor": "outdoors", "inside": "indoors", "outside": "outdoors", "lit": "", "night time": "night",
       "nighttime": "night", "daytime": "day"}
_HAIR_EYE = re.compile(r"^([a-z]+) (hair|eyes)$")


def _salvage(t: str) -> str | None:
    """"oversized armchair" -> "armchair": keep the longest tail (then head) of a compound that is a real, common tag."""
    w = t.split(" ")
    if len(w) < 2:
        return None
    cands = [" ".join(w[k:]) for k in range(1, len(w))] + [" ".join(w[:k]) for k in range(len(w) - 1, 0, -1)]
    for c in cands:
        if c in QUALITY or c in VAGUE or len(c) < 3:
            continue
        r = tagdb.lookup(c, fuzzy=False, aliases=False)
        if r and tagdb.count(r) >= 1000 and tagdb.category(r) in ("general", "species") and r not in QUALITY | VAGUE:
            return r
    return None


_CTX = {"text": ""}


def check_tag(raw: str, rating: str, fixed: list, dropped: list, reasons: dict) -> str | None:
    """One candidate tag -> canonical tag, or None (recorded in dropped/reasons)."""
    t = tagdb.normalise(raw)
    if not t:
        return None
    t = FIX.get(t, t) or t
    m = _HAIR_EYE.match(t)
    if m and m.group(1) in COLOUR_SYN and (m.group(2) == "hair" or tagdb.info(t) is None):
        t = f"{COLOUR_SYN[m.group(1)]} {m.group(2)}"

    def drop(why):
        if t not in dropped:
            dropped.append(t)
        reasons[t] = why
    if t.startswith(("score_", "source_", "rating_")):
        return None
    if t in QUALITY:
        drop("quality word (score tags cover it)")
        return None
    if t in PERSON_WORDS and not re.search(r"anthro|furry", _CTX["text"]):
        drop("person word (the count tag covers it)")
        return None
    if t in VAGUE:
        drop("too vague to be a tag")
        return None
    t0 = t
    canon = tagdb.lookup(t)
    if canon is None:
        canon = _salvage(t)
    if canon is None:
        t = t0
        drop("not a known booru tag")
        return None
    if canon in QUALITY or canon in VAGUE:
        drop("quality/vague word")
        return None
    cat = tagdb.category(canon)
    if cat == "artist":
        drop("artist tag")
        return None
    if cat in ("meta", "lore") and canon not in KEEP_META and not is_count(canon):
        drop("meta tag")
        return None
    if rating == "safe" and canon in SAFE_REMOVE:
        drop("not allowed at rating safe")
        return None
    if canon != t:
        fixed.append({"from": t, "to": canon})
    return canon


def finish(data: dict, text: str, source: str = "anime", rating: str = "safe") -> dict:
    """Model JSON ({tags, characters, rating_hint}) -> final Pony prompt dict."""
    fixed: list[dict] = []
    dropped: list[str] = []
    reasons: dict[str, str] = {}
    tags: list[str] = []
    low = text.lower()
    _CTX["text"] = low
    for name in data.get("characters") or []:
        n = tagdb.normalise(name)
        if n and n in low:
            c = tagdb.lookup(n, fuzzy=False)
            if c and tagdb.category(c) in ("character", "copyright"):
                tags.append(c)
    for raw in data.get("tags") or []:
        c = check_tag(str(raw), rating, fixed, dropped, reasons)
        if c:
            tags.append(c)
    inferred = infer_count(text)
    have_people = [t for t in tags if is_count(t) and t != "no humans"]
    if inferred:
        if not have_people and "no humans" not in tags:
            tags = inferred + tags
        elif inferred == ["no humans"] and not have_people:
            pass
        elif "no humans" in tags and inferred != ["no humans"]:
            tags = [t for t in tags if t != "no humans"] + inferred
        elif inferred == ["no humans"] and have_people:
            tags = [t for t in tags if t not in have_people] + inferred
        elif set(inferred) != set(have_people) and all(re.match(r"^[2-9](girl|boy)s$|^multiple", c) for c in inferred if "girl" in c or "boy" in c) and len(inferred) >= len(have_people):
            tags = [t for t in tags if t not in have_people] + inferred
    tags = enrich(tags, text, rating)
    final = assemble(tags, source, rating)
    return {"prompt": ", ".join(final), "negative": suggest_negative(source, rating, final), "tags": final,
            "dropped": dropped, "dropped_reasons": reasons, "fixed": fixed,
            "rating_hint": data.get("rating_hint") or "", "note": ""}
