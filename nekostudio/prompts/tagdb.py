"""Booru tag dictionary: real vocabulary (danbooru + e621) with post counts and aliases.

Sources, first found wins per file: <models>/tags/danbooru.csv and e621.csv (a1111-tagcomplete lists:
`name,type,count,"alias1,alias2"`), else the WD tagger's selected_tags.csv from the HF cache.
Everything is loaded lazily and cached. Tags use spaces, never underscores (score_9 style tags excepted).
"""
from __future__ import annotations

import csv
import difflib
import re
import threading
from pathlib import Path

from .. import config

# danbooru type ids -> category; e621 uses a different numbering
_DAN_CAT = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}
_E6_CAT = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "species", 7: "meta", 8: "lore"}
_WD_CAT = {0: "general", 4: "character", 9: "meta"}
FUZZY_MIN_COUNT = 50
FUZZY_RATIO = 0.9
# tags that are valid for the model but are not in booru lists as such
EXTRA = {"score_9", "score_8_up", "score_7_up", "score_6_up", "score_5_up", "score_4_up",
         "source_anime", "source_cartoon", "source_furry", "source_pony",
         "rating_safe", "rating_questionable", "rating_explicit"}
# our own preferences: tags a model trained on danbooru handles better than the raw alias target
KEEP = {"silver hair": 150000, "gold hair": 1000, "golden hair": 1000, "glowing sword": 800, "glowing weapon": 800}
PREFER = {"1girls": "1girl", "1boys": "1boy"}

_lock = threading.Lock()
_db: dict | None = None


def normalise(tag: str) -> str:
    """lowercase, underscores -> spaces, strip emphasis weights, parentheses escapes and stray punctuation."""
    t = str(tag).strip().lower()
    if t.startswith(("score_", "source_", "rating_")):
        return re.sub(r"[^a-z0-9_]", "", t)
    t = t.replace("\\(", "(").replace("\\)", ")")
    t = re.sub(r":\s*-?\d+(\.\d+)?(?=[)\]}]*$)", "", t)   # (tag:1.2)
    t = t.strip(" \t\"'.;:!?<>")
    for _ in range(4):        # emphasis wrappers ((tag)), [tag], {tag}; "name (series)" keeps its parentheses
        if len(t) > 1 and t[0] in "([{" and t[-1] in ")]}":
            t = t[1:-1].strip()
        else:
            break
    if t.count("(") != t.count(")"):
        t = t.strip("()[]{}")
    t = t.replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _paths() -> dict[str, Path]:
    out = {}
    for n in ("danbooru", "e621"):
        p = config.TAGS / f"{n}.csv"
        if p.is_file():
            out[n] = p
    return out


def _wd_csv() -> Path | None:
    hub = config.HF_HOME / "hub"
    for p in sorted(hub.glob("models--SmilingWolf--*/snapshots/*/selected_tags.csv")):
        return p
    return None


def available() -> bool:
    return bool(_paths()) or _wd_csv() is not None


def full() -> bool:
    """Both real tag lists present (otherwise the quality of translation drops)."""
    return len(_paths()) == 2


def _reset():
    global _db
    with _lock:
        _db = None


def _add(db, name, cat, count, aliases, src):
    name = normalise(name)
    if not name:
        return
    cur = db["tags"].get(name)
    if cur is None or (src == "danbooru" and cur[2] != "danbooru"):
        db["tags"][name] = (cat, count, src)
    elif cur[2] == src or True:
        # same tag in both lists: keep the larger count, prefer the danbooru category
        db["tags"][name] = (cur[0], max(cur[1], count), cur[2])
    for a in aliases:
        a = normalise(a)
        if a and a != name:
            db["alias_raw"].append((a, name, count))


def _load() -> dict:
    global _db
    with _lock:
        if _db is not None:
            return _db
        db = {"tags": {}, "alias_raw": [], "alias": {}, "words": {}, "sources": []}
        for src, p in _paths().items():
            cats = _DAN_CAT if src == "danbooru" else _E6_CAT
            with open(p, newline="", encoding="utf-8", errors="replace") as f:
                for row in csv.reader(f):
                    if len(row) < 3:
                        continue
                    try:
                        typ, count = int(row[1]), int(row[2])
                    except ValueError:
                        continue
                    cat = cats.get(typ)
                    if cat is None:
                        continue
                    al = [x for x in row[3].split(",") if x] if len(row) > 3 else []
                    _add(db, row[0], cat, count, al, src)
            db["sources"].append(src)
        if not db["tags"]:
            p = _wd_csv()
            if p:
                with open(p, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        try:
                            cat = _WD_CAT.get(int(row["category"]))
                            count = int(row.get("count") or 0)
                        except (ValueError, KeyError):
                            continue
                        if cat:
                            _add(db, row["name"], cat, count, [], "wd")
                db["sources"].append("wd14")
        for t, c in KEEP.items():
            db["tags"].setdefault(t, ("general", c, "builtin"))
        for t in EXTRA:
            db["tags"][t] = ("meta", 10**9, "builtin")
        # aliases: never override a real tag; the most popular target wins
        alias = db["alias"]
        best: dict[str, int] = {}
        for a, name, count in db["alias_raw"]:
            if a in db["tags"]:
                continue
            if count >= best.get(a, -1):
                best[a] = count
                alias[a] = name
        db["alias_raw"] = []
        for k, v in PREFER.items():
            alias[k] = v
        # index for word-order swaps and fuzzy matching
        db["bylen"] = {}
        for t, (cat, count, _s) in db["tags"].items():
            if count >= FUZZY_MIN_COUNT and cat in ("general", "species", "character", "copyright"):
                db["bylen"].setdefault(len(t), []).append(t)
        db["sorted_words"] = {}
        for t, (cat, count, _s) in db["tags"].items():
            if " " in t and count >= 5 and cat in ("general", "species"):
                db["sorted_words"].setdefault(" ".join(sorted(t.split())), t)
        _db = db
        return db


def info(tag: str) -> tuple[str, int] | None:
    """(category, count) of an exact tag."""
    db = _load()
    e = db["tags"].get(normalise(tag))
    return (e[0], e[1]) if e else None


def category(tag: str) -> str | None:
    i = info(tag)
    return i[0] if i else None


def count(tag: str) -> int:
    i = info(tag)
    return i[1] if i else 0


def is_tag(tag: str) -> bool:
    return normalise(tag) in _load()["tags"]


def _variants(t: str):
    """plural / singular forms of the last word."""
    words = t.split(" ")
    w = words[-1]
    cands = []
    if w.endswith("ies") and len(w) > 4:
        cands.append(w[:-3] + "y")
    if w.endswith("es") and len(w) > 3:
        cands.append(w[:-2])
    if w.endswith("s") and not w.endswith("ss") and len(w) > 2:
        cands.append(w[:-1])
    if not w.endswith("s"):
        cands += [w + "s", w + "es"]
        if w.endswith("y"):
            cands.append(w[:-1] + "ies")
    for c in cands:
        yield " ".join(words[:-1] + [c])


def lookup(tag: str, fuzzy: bool = True, aliases: bool = True) -> str | None:
    """Canonical tag for `tag` or None. exact -> alias -> plural/singular -> word order -> conservative fuzzy."""
    t = normalise(tag)
    if not t:
        return None
    db = _load()
    tags, alias = db["tags"], db["alias"]
    if t in tags:
        c = tags[t][1]
        if c < 300:      # rare form ("rooftops" 40) next to a far more common one ("rooftop")
            for v in _variants(t):
                if v in tags and tags[v][1] > c * 10:
                    return v
        return t
    if aliases and t in alias:
        return alias[t]
    for v in _variants(t):
        if v in tags:
            return v
        if aliases and v in alias:
            return alias[v]
    words = t.split(" ")
    if 2 <= len(words) <= 3:
        hit = db["sorted_words"].get(" ".join(sorted(words)))
        if hit:
            return hit
    if fuzzy and len(t) >= 5:
        n = len(t)
        best, best_r = None, FUZZY_RATIO
        sm = difflib.SequenceMatcher(autojunk=False)
        sm.set_seq2(t)
        for L in range(n - 2, n + 3):
            for c in db["bylen"].get(L, ()):
                sm.set_seq1(c)
                if sm.real_quick_ratio() < best_r or sm.quick_ratio() < best_r:
                    continue
                r = sm.ratio()
                if r > best_r or (r == best_r and best and tags[c][1] > tags[best][1]):
                    best, best_r = c, r
        if best and best.split(" ")[0][:2] == t.split(" ")[0][:2]:
            return best
    return None


def sources() -> list[str]:
    return list(_load()["sources"])


def stats() -> dict:
    db = _load()
    return {"tags": len(db["tags"]), "aliases": len(db["alias"]), "sources": db["sources"]}


if __name__ == "__main__":
    import time
    t0 = time.time()
    print(stats(), round(time.time() - t0, 1), "s")
    for q in ["Long_Hair", "(silver hair:1.2)", "hair long", "cherry blossom", "1girls", "armchairs", "mist", "fox girl",
              "flowing", "masterpiece", "score_9", "gold coins", "white bikini", "pointed ears", "spellbook"]:
        print(f"{q!r:24} -> {lookup(q)!r} {category(lookup(q) or '')}")
