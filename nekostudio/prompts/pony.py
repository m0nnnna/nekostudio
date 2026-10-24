"""Rule-based prose -> Pony/booru tag translator (fallback when no local LLM is installed).

Everything it emits is a real tag from the tag dictionary (tagdb): the prose is normalised, then
matched greedily left to right with the longest n-gram first (curated phrase table, then the
dictionary with simple lemmatisation), colour+hair/eyes phrases are composed ("auburn hair" ->
"brown hair"), the character count comes from the person nouns and pronouns, and anything that
is not a real tag goes to `dropped` instead of being emitted as a fragment.
"""
from __future__ import annotations

import re
import unicodedata

from . import phrases, postproc, tagdb
from .postproc import COLOUR_SYN, RATINGS, SCORE_TAGS, SOURCE_TAGS, assemble, suggest_negative  # noqa: F401 (re-exported)

# ---------------------------------------------------------------------------------------------
# tokenizer
# ---------------------------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-z0-9]+|[,;.!?:\n]")
_SKIP = {"a", "an", "the", "her", "his", "their", "its", "my", "our", "some", "this", "that", "these", "those"}
_BREAK = set(",;.!?:\n")
_LEADIN_RE = re.compile(
    r"\b(?:there (?:is|are)|(?:an? )?(?:image|picture|photo|photograph|illustration|render|shot) of|"
    r"showing|featuring|depicting|shows|features)\b")
_INSTR_RE = re.compile(r"^\s*(?:please\s+)?(?:create|draw|generate|make|paint|render|illustrate|produce|show|design)\s+(?:me\s+)?(?:an?\s+)?", re.I)


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = _INSTR_RE.sub("", text.lower().replace("’", "'"))
    text = re.sub(r"'s\b", "", text).replace("'", "")
    text = _LEADIN_RE.sub(" , ", text.replace("-", " ").replace("/", " "))
    text = text.replace("(", " , ").replace(")", " , ")
    return [t for t in _TOKEN_RE.findall(text) if t not in _SKIP]


def _parse_table(raw: str) -> dict[tuple[str, ...], list[str]]:
    out = {}
    for line in raw.strip().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, _, val = line.partition(":")
        toks = tuple(t for t in tokenize(key) if t not in _BREAK)
        if toks:
            out[toks] = [v.strip() for v in val.split(",") if v.strip()]
    return out


PHRASES = _parse_table(phrases.TABLE)
PHRASES[("tongue", "out")] = [":p"]   # the tag starts with ':' so it cannot live in the text table
_MAX_N = 4

# ---------------------------------------------------------------------------------------------
# vocabulary rules
# ---------------------------------------------------------------------------------------------
COLOURS = set(COLOUR_SYN) | {"black", "white", "red", "blue", "green", "yellow", "pink", "purple", "orange", "brown", "grey",
                             "silver", "blonde", "aqua", "beige", "multicolored"}
EYE_COLOUR_SYN = {"blonde": "yellow", "silver": "grey", "golden": "yellow", "gold": "yellow"}
LENGTH = {"long": "long", "short": "short", "medium": "medium", "shoulder": "medium", "waist": "very long", "flowing": "long",
          "cascading": "long", "shoulderlength": "medium", "knee": "very long", "cropped": "short", "shaggy": "messy", "tousled": "messy"}
HAIR_STYLE = {"wavy", "curly", "straight", "messy", "spiky", "braided", "fluffy", "silky", "wild", "shiny"}
FILLER = {"very", "piercing", "bright", "big", "large", "soft", "deep", "dark", "light", "pale", "vivid", "striking", "stunning",
          "beautiful", "lovely", "gorgeous", "pretty", "thick", "thin", "glossy", "radiant", "intense", "warm", "cold", "sharp",
          "shiny", "luminous", "rich", "dull", "faded", "ornate", "shimmering", "glittering", "sparkling", "glowing", "bright"}
_STOP = set("""with and in on at of to for by is are was were be being been it she he they them who that which this
into onto over under from as while his her their its out up down off across through between around near around""".split())
_PREP_STOP = _STOP | {"wearing", "has", "have", "having", "holding"}
_NOUN_BAN = set(postproc.QUALITY | postproc.VAGUE | COLOURS | {"bound", "tied", "light", "lighting", "lit", "wearing", "worn",
                "like", "very", "just", "also", "style", "looking", "view", "focus", "space", "case", "back", "front", "side",
                "top", "lot", "way", "time", "feel", "feeling", "mood", "vibe", "scene", "moment", "world", "place", "air", "tall",
                "round", "long", "short", "little", "small", "big", "large", "old", "new", "young", "tiny", "giant", "huge",
                "holding", "flashing", "cast", "nostril", "nostrils", "dark", "bright", "pale", "tired", "ancient", "lone", "lonely", "wooden", "stone", "metal", "paper", "glass"})
_VERB_S = set("""spills streaks casts hands sleeps stands sits holds wears lies falls rises glows shines flows reflects hangs rests
curls drips blows fills covers surrounds sports carries shows looks stares watches reaches runs walks makes takes gives lets
sends brings keeps turns pulls pushes drapes spreads stretches wraps catches leads follows rolls bursts shoots rains snows""".split())
STYLE_HEADS = ("twintails", "ponytail", "pigtails", "braid", "braids", "bun", "bob", "bangs", "twintail")
_WEAPONS = {"sword": "sword", "katana": "sword", "blade": "sword", "dagger": "dagger", "spear": "spear", "staff": "staff",
            "axe": "axe", "bow": "bow (weapon)", "gun": "gun", "rifle": "rifle", "pistol": "handgun", "wand": "wand",
            "lantern": "lantern", "umbrella": "umbrella", "book": "book", "cup": "cup", "mug": "cup", "flower": "flower"}
_HOLD = {"holding", "wielding", "gripping", "brandishing", "carrying", "drawn", "draws", "drawing", "unsheathed", "unsheathing",
         "swinging", "clutching", "raising", "raised", "slashing", "hold", "holds"}


def _stem_candidates(w: str):
    yield w
    for suf in ("ing", "ed"):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            s = w[:-len(suf)]
            yield s
            yield s + "e"
            if len(s) > 2 and s[-1] == s[-2]:
                yield s[:-1]
            if s.endswith("i"):
                yield s[:-1] + "y"


def _ok_category(canon: str, n: int) -> bool:
    cat = tagdb.category(canon)
    if n == 1:
        return cat in ("general", "species")
    return cat in ("general", "species", "character", "copyright")


def _match_dict(words: list[str]) -> str | None:
    """Dictionary tag for a window of words, or None."""
    n = len(words)
    s = " ".join(words)
    if n == 1:
        w = words[0]
        if w in _NOUN_BAN or w in _STOP or w in _VERB_S or len(w) < 3 or w.isdigit():
            return None
        for cand in _stem_candidates(w):
            if cand in _NOUN_BAN:
                continue
            c = tagdb.lookup(cand, fuzzy=False, aliases=False)
            if c is None:
                a = tagdb.lookup(cand, fuzzy=False)
                # an alias is only trusted when it is the same word ("sleep" -> "sleeping")
                c = a if a and a[:4] == cand[:4] and a != "butt" else None
            if c and tagdb.count(c) >= 500 and _ok_category(c, 1) and c not in _NOUN_BAN:
                return c
        return None
    if any(w in _STOP for w in (words[0], words[-1])) or any(w in _VERB_S for w in words[:-1]):
        return None
    c = tagdb.lookup(s, fuzzy=False)
    if c and tagdb.count(c) >= 20 and _ok_category(c, n):
        return c
    return None


def _hair_eyes(tokens: list[str], used: list[bool]) -> list[tuple[int, list[str]]]:
    """Compose colour/length/style words in front of hair / eyes into tags. Returns (start, tags) and marks tokens used."""
    out = []
    for h, tok in enumerate(tokens):
        if tok not in ("hair", "eyes", "eye", "fur") + STYLE_HEADS or used[h]:
            continue
        j, mods = h - 1, []
        while j >= 0 and len(mods) < 5 and tokens[j] not in _BREAK and tokens[j] not in _PREP_STOP and not used[j]:
            mods.append(tokens[j])
            j -= 1
        # a "black and white hair" style conjunction is allowed through
        mods.reverse()
        start = j + 1
        tags: list[str] = []
        head_tag = tok in STYLE_HEADS
        kind = "eyes" if tok.startswith("eye") else "hair" if head_tag else tok
        # keep only the trailing run of words that look like hair/eye modifiers
        keep = []
        for m in reversed(mods):
            if m in COLOURS or m in LENGTH or m in HAIR_STYLE or m in FILLER or m in ("and", "two", "tone", "multi", "colored"):
                keep.append(m)
            else:
                break
        keep.reverse()
        start = h - len(keep)
        for m in keep:
            if kind == "hair" or kind == "fur":
                if m in LENGTH:
                    tags.append(f"{LENGTH[m]} hair" if kind == "hair" else "")
                elif m in HAIR_STYLE:
                    tags.append(f"{m} hair")
                elif m in COLOURS and m not in ("silver",) or m == "silver":
                    c = COLOUR_SYN.get(m, m)
                    tags.append(f"{c} {kind}")
            else:
                if m in COLOURS:
                    c = EYE_COLOUR_SYN.get(m) or COLOUR_SYN.get(m, m)
                    tags.append(f"{c} eyes")
                elif m in ("glowing", "sparkling"):
                    tags.append(f"{m} eyes")
        good = []
        if head_tag:
            tags.append(tok)
        for t in tags:
            c = tagdb.lookup(t, fuzzy=False, aliases=False) if t else None
            if c and c not in good:
                good.append(c)
        # "blonde hair" beats "yellow hair"; drop the generic when a specific colour exists
        if good or keep:
            for k in range(start, h + 1):
                used[k] = True
            out.append((start, good))
    return out


def prose_to_tags(text: str) -> tuple[list[str], list[str]]:
    """-> (tags, dropped). Tags are dictionary-validated; dropped are content words that did not map."""
    tokens = tokenize(text)
    used = [False] * len(tokens)
    found: dict[int, list[str]] = {}
    dropped: list[str] = []
    for start, tg in _hair_eyes(tokens, used):
        found.setdefault(start, []).extend(tg)
    i = 0
    while i < len(tokens):
        if used[i] or tokens[i] in _BREAK:
            i += 1
            continue
        hit = None
        for n in range(min(_MAX_N, len(tokens) - i), 0, -1):
            win = tokens[i:i + n]
            if any(used[i + k] or win[k] in _BREAK for k in range(n)):
                continue
            if tuple(win) in PHRASES:
                hit = (n, [t for t in PHRASES[tuple(win)]], True)
                break
            c = _match_dict(win)
            if c:
                hit = (n, [c], False)
                break
            if n == 3:   # "glowing blue sword" -> "glowing sword": a colour in the middle is skipped
                if win[1] in COLOURS:
                    c = _match_dict([win[0], win[2]])
                    if c:
                        hit = (n, [c], False)
                        break
        if hit:
            n, tg, curated = hit
            for k in range(n):
                used[i + k] = True
            if not tg and curated:
                dropped.append(" ".join(tokens[i:i + n]))
            found.setdefault(i, []).extend(tg)
            i += n
        else:
            w = tokens[i]
            if w not in _STOP and w not in COLOURS and len(w) > 2 and not w.isdigit() and w not in _SKIP:
                dropped.append(w)
            i += 1
    tags = [t for k in sorted(found) for t in found[k]]
    return tags, dropped


def _cleanup(tags: list[str], dropped: list[str], rating: str) -> tuple[list[str], list[dict], dict]:
    fixed: list[dict] = []
    reasons: dict[str, str] = {}
    out = []
    for t in tags:
        if postproc.is_count(t) or t == "solo":
            out.append(t)
            continue
        c = postproc.check_tag(t, rating, fixed, dropped, reasons)
        if c:
            out.append(c)
    return out, fixed, reasons


def translate(text: str, source: str = "anime", rating: str = "safe") -> dict:
    tags, dropped = prose_to_tags(text)
    # character count: from person nouns / pronouns; table-supplied counts only when nothing could be inferred
    inferred = postproc.infer_count(text)
    table_counts = [t for t in tags if postproc.is_count(t)]
    tags = [t for t in tags if not postproc.is_count(t) and t != "solo"]
    counts = inferred or table_counts
    tags, fixed, reasons = _cleanup(tags, dropped, rating)
    tags = counts + tags
    tags = postproc.enrich(tags, text, rating)
    final = assemble(tags, source, rating)
    dropped = [d for d in dict.fromkeys(dropped) if d not in final]
    return {"prompt": ", ".join(final), "negative": suggest_negative(source, rating, final), "tags": final,
            "dropped": dropped, "dropped_reasons": reasons, "fixed": fixed, "engine": "rules", "note": ""}


if __name__ == "__main__":
    sample = ("A beautiful anime girl with long silver hair and red eyes, smiling, standing in a cherry blossom "
              "forest at sunset, wearing a black kimono, highly detailed, full body shot")
    r = translate(sample, "anime", "safe")
    print(r["prompt"])
    print("dropped:", r["dropped"])
    must = ["score_9", "source_anime", "rating_safe", "1girl", "solo", "long hair", "silver hair", "red eyes", "smile",
            "standing", "cherry blossoms", "forest", "outdoors", "sunset", "black kimono", "full body"]
    missing = [t for t in must if t not in r["tags"]]
    assert not missing, missing
    assert r["tags"][:5] == ["score_9", "score_8_up", "score_7_up", "source_anime", "rating_safe"], r["tags"][:5]
    two = translate("two girls and a cat sitting on a wooden bench, blue sky, wearing red dresses", "cartoon")
    assert "2girls" in two["tags"] and "solo" not in two["tags"], two["tags"]
    print("pony self-test: ok (%d phrases)" % len(PHRASES))
