"""Rule-based prose -> Pony/booru tag translator. No network, no dependencies.

Pipeline: tokenize -> greedy left-to-right matching (dynamic hair/eye/garment rules, then the
phrase table, longest phrase first) -> leftover "adjective noun" chunks become tags, filler goes to
`dropped` -> assemble in Pony order (score, source, rating, character count, rest).
"""
from __future__ import annotations

import re

SCORE_TAGS = ["score_9", "score_8_up", "score_7_up"]
SOURCE_TAGS = {"anime": "source_anime", "cartoon": "source_cartoon", "furry": "source_furry",
               "pony": "source_pony", "realistic": None}
RATINGS = {"safe": "rating_safe", "questionable": "rating_questionable", "explicit": "rating_explicit"}

# --------------------------------------------------------------------------------------------
# Phrase table. "prose phrase: tag, tag"; an empty right side means "drop and report".
# Keys are written without articles/possessives (those are removed while tokenizing).
# --------------------------------------------------------------------------------------------
_TABLE = """
# characters and counts
girl: 1girl
woman: 1girl
lady: 1girl
female: 1girl
young woman: 1girl
young lady: 1girl
anime girl: 1girl
schoolgirl: 1girl, school uniform
maiden: 1girl
princess: 1girl, princess
queen: 1girl, crown
boy: 1boy
man: 1boy
guy: 1boy
male: 1boy
young man: 1boy
gentleman: 1boy
anime boy: 1boy
prince: 1boy, prince
king: 1boy, crown
one girl: 1girl
1 girl: 1girl
one boy: 1boy
1 boy: 1boy
two girls: 2girls
2 girls: 2girls
three girls: 3girls
3 girls: 3girls
four girls: 4girls
five girls: 5girls
two boys: 2boys
2 boys: 2boys
three boys: 3boys
group of girls: multiple girls
group of boys: multiple boys
girls: multiple girls
boys: multiple boys
couple: 1girl, 1boy
lovers: 1girl, 1boy
little girl: 1girl, child
little boy: 1boy, child
child: child
old man: 1boy, old man
old woman: 1girl, old woman
elderly man: 1boy, old man
elderly woman: 1girl, old woman
mature woman: 1girl, mature female
no people: no humans
no humans: no humans
alone: solo
solo: solo
lone: solo
by herself: solo
by himself: solo
catgirl: 1girl, cat ears, cat tail
cat girl: 1girl, cat ears, cat tail
fox girl: 1girl, fox ears, fox tail
wolf girl: 1girl, wolf ears, wolf tail
bunny girl: 1girl, rabbit ears, rabbit tail
demon girl: 1girl, demon horns, demon tail
elf: elf, pointy ears
angel: angel, angel wings, halo
vampire: vampire
witch: witch, witch hat
mermaid: mermaid
robot: robot
android: android
cyborg: cyborg
maid: maid
nurse: nurse
knight: knight
samurai: samurai
ninja: ninja
idol: idol
pirate: pirate
shrine maiden: miko
priestess: miko
fairy: fairy, fairy wings
dragon girl: 1girl, dragon horns, dragon tail
# hair beyond the dynamic colour+length rule
ponytail: ponytail
high ponytail: high ponytail
side ponytail: side ponytail
twin tails: twintails
twintails: twintails
pigtails: twintails
braid: braid
braids: braid
twin braids: twin braids
side braid: side braid
french braid: french braid
bun: hair bun
hair bun: hair bun
messy bun: hair bun, messy hair
double bun: double bun
bangs: bangs
blunt bangs: blunt bangs
side bangs: swept bangs
hair between eyes: hair between eyes
ahoge: ahoge
bob cut: bob cut
hime cut: hime cut
drill hair: drill hair
twin drills: twin drills
hair ribbon: hair ribbon
hair bow: hair bow
hair ornament: hair ornament
hair flower: hair flower
hair over one eye: hair over one eye
sidelocks: sidelocks
very long hair: very long hair
shoulder length hair: medium hair
bald: bald
undercut: undercut
ahoge hair: ahoge
two tone hair: two-tone hair
gradient hair: gradient hair
rainbow hair: multicolored hair
multicolored hair: multicolored hair
windblown hair: wind
hair blowing in wind: wind
wet hair: wet hair
hair down: hair down
# eyes and expressions
heterochromia: heterochromia
closed eyes: closed eyes
eyes closed: closed eyes
half closed eyes: half-closed eyes
wide eyes: wide-eyed
glowing eyes: glowing eyes
sparkling eyes: sparkling eyes
empty eyes: empty eyes
narrowed eyes: narrowed eyes
slit pupils: slit pupils
heart shaped pupils: heart-shaped pupils
one eye closed: one eye closed
wink: wink
winking: wink
smiling: smile
smile: smile
smiles: smile
happy: happy, smile
grinning: grin
grin: grin
laughing: laughing, open mouth, smile
gentle smile: light smile
soft smile: light smile
warm smile: smile
slight smile: light smile
smirking: smirk
smirk: smirk
sad: sad
crying: crying, tears
tears: tears
teary eyed: tears
angry: angry
blushing: blush
blush: blush
embarrassed: embarrassed, blush
shy: shy
surprised: surprised, open mouth
scared: scared
serious: serious
expressionless: expressionless
neutral expression: expressionless
pouting: pout
pout: pout
sleepy: sleepy
determined: determined
open mouth: open mouth
closed mouth: closed mouth
tongue out: :p
fang: fang
looking at viewer: looking at viewer
looking at camera: looking at viewer
eye contact: looking at viewer
looking away: looking away
looking back: looking back
looking up: looking up
looking down: looking down
looking to the side: looking to the side
looking at the side: looking to the side
# poses and actions
standing: standing
sitting: sitting
seated: sitting
kneeling: kneeling
lying: lying
lying down: lying
on back: on back
on stomach: on stomach
crouching: crouching
squatting: squatting
walking: walking
running: running
jumping: jumping
flying: flying
floating: floating
dancing: dancing
singing: singing
sleeping: sleeping
reading: reading
leaning forward: leaning forward
arms up: arms up
arms behind back: arms behind back
arms crossed: crossed arms
crossed arms: crossed arms
hands on hips: hands on hips
hand on hip: hand on hip
hand on chest: hand on own chest
hands clasped: own hands clasped
waving: waving
peace sign: v
v sign: v
holding hands: holding hands
hugging: hugging
stretching: stretching
sitting on bed: sitting, on bed
sitting on chair: sitting, chair
head tilt: head tilt
from behind: from behind
dynamic pose: dynamic pose
action pose: dynamic pose
# camera and framing
full body: full body
full body shot: full body
whole body: full body
upper body: upper body
upper body shot: upper body
waist up: upper body
bust shot: upper body
bust: upper body
portrait: portrait
headshot: portrait
face focus: face focus
close up: close-up
close up shot: close-up
extreme close up: close-up
cowboy shot: cowboy shot
half body: upper body
wide shot: wide shot
wide angle: wide shot
long shot: wide shot
dutch angle: dutch angle
from above: from above
from below: from below
from side: from side
from the side: from side
side view: from side
low angle: from below
high angle: from above
birds eye view: from above
bird eye view: from above
worm eye view: from below
top down view: from above
front view: facing viewer
pov: pov
first person view: pov
depth of field: depth of field
bokeh: bokeh
blurry background: blurry background
motion blur: motion blur
lens flare: lens flare
fisheye: fisheye
symmetrical: symmetry
centered: 
# clothing extras (colour + garment is handled dynamically)
bare shoulders: bare shoulders
off shoulder: off shoulder
barefoot: barefoot
long sleeves: long sleeves
short sleeves: short sleeves
sleeveless: sleeveless
detached sleeves: detached sleeves
wide sleeves: wide sleeves
sailor uniform: serafuku
sailor collar: sailor collar
maid outfit: maid, maid headdress
maid dress: maid, maid headdress
witch hat: witch hat
sun hat: sun hat
straw hat: straw hat
baseball cap: baseball cap
high heels: high heels
fingerless gloves: fingerless gloves
trench coat: trench coat
leather jacket: leather jacket
hooded cloak: hooded cloak
plate armor: armor
wedding dress: wedding dress
evening gown: evening gown
formal wear: formal
one piece swimsuit: one-piece swimsuit
swimsuit: swimsuit
bikini: bikini
casual clothes: casual
casual wear: casual
traditional clothes: traditional clothes
traditional japanese clothing: japanese clothes
japanese clothes: japanese clothes
miko outfit: miko
cat ear headphones: cat ear headphones
cleavage: cleavage
thigh highs: thighhighs
knee highs: kneehighs
jewelry: jewelry
glasses: glasses
sunglasses: sunglasses
eyepatch: eyepatch
earrings: earrings
necklace: necklace
# settings and locations
forest: forest, outdoors
in forest: forest, outdoors
cherry blossom forest: cherry blossoms, forest, outdoors
cherry blossom tree: cherry blossoms, tree
cherry blossom trees: cherry blossoms, tree
cherry blossoms: cherry blossoms
cherry blossom: cherry blossoms
sakura: cherry blossoms
sakura petals: cherry blossoms, petals
bamboo forest: bamboo forest, outdoors
jungle: jungle, outdoors
garden: garden, outdoors
flower field: flower field, outdoors
field: field, outdoors
meadow: field, outdoors
grassy field: field, grass, outdoors
beach: beach, outdoors
ocean: ocean
sea: ocean
lake: lake, outdoors
river: river, outdoors
waterfall: waterfall, outdoors
mountains: mountain, outdoors
mountain: mountain, outdoors
snowy mountain: mountain, snow, outdoors
desert: desert, outdoors
cave: cave
island: island
cliff: cliff
city: city, outdoors
cityscape: cityscape
city street: street, city, outdoors
street: street, outdoors
alley: alley
rooftop: rooftop, outdoors
bridge: bridge
skyscraper: skyscraper
neon city: city, neon lights, night
cyberpunk city: cyberpunk, city, neon lights
village: village, outdoors
town: town, outdoors
castle: castle
temple: temple
shrine: shrine
torii gate: torii
torii: torii
pagoda: pagoda
ruins: ruins
church: church
cathedral: cathedral
library: library, indoors
classroom: classroom, indoors
school: school
bedroom: bedroom, indoors
living room: living room, indoors
room: indoors
kitchen: kitchen, indoors
bathroom: bathroom, indoors
cafe: cafe, indoors
restaurant: restaurant, indoors
office: office, indoors
indoors: indoors
outdoors: outdoors
balcony: balcony
window: window
stage: stage
spaceship: spacecraft
space: space
starry sky: starry sky
night sky: night sky
sky: sky
clouds: cloud
cloudy sky: cloudy sky, cloud
blue sky: blue sky, cloud
rain: rain
raining: rain
snow: snow
snowing: snowing, snow
fog: fog
foggy: fog
storm: storm
autumn leaves: autumn leaves
autumn: autumn
winter: winter
summer: summer
spring: spring
petals: petals
falling petals: falling petals, petals
fireflies: fireflies
fireworks: fireworks
lanterns: lantern
paper lantern: paper lantern
festival: festival
water: water
underwater: underwater
simple background: simple background
white background: white background
black background: black background
gradient background: gradient background
abstract background: abstract background
# lighting and time of day
at night: night
night: night
nighttime: night
daytime: day
day: day
morning: morning
evening: evening
dusk: dusk
twilight: twilight
sunset: sunset
sunrise: sunrise
golden hour: sunset, sunlight
sunlight: sunlight
moonlight: moonlight
moon: moon
full moon: full moon
stars: star (sky)
soft lighting: soft lighting
dramatic lighting: dramatic lighting
cinematic lighting: cinematic lighting
backlighting: backlighting
rim lighting: rim lighting
neon lights: neon lights
volumetric lighting: light rays
god rays: light rays
glowing: glowing
shadows: shadow
dark: dark
colorful: colorful
vibrant colors: colorful
pastel colors: pastel colors
monochrome: monochrome
greyscale: greyscale
sepia: sepia
# art styles
anime style: anime
anime: anime
cartoon style: cartoon
photorealistic: realistic, photorealistic
photo realistic: realistic, photorealistic
realistic: realistic
hyperrealistic: realistic, photorealistic
3d render: 3d
3d: 3d
pixel art: pixel art
watercolor: watercolor (medium)
watercolor painting: watercolor (medium)
oil painting: oil painting (medium)
sketch: sketch
line art: lineart
lineart: lineart
manga: manga
comic: comic
chibi: chibi
flat color: flat color
cel shading: cel shading
ghibli style: studio ghibli
studio ghibli: studio ghibli
ukiyo e: ukiyo-e
minimalist: minimalism
steampunk: steampunk
cyberpunk: cyberpunk
fantasy: fantasy
sci fi: science fiction
magical girl: magical girl
gothic: gothic
retro anime: retro artstyle
# animals, ears, tails, wings
cat ears: cat ears
cat tail: cat tail
fox ears: fox ears
fox tail: fox tail
wolf ears: wolf ears
wolf tail: wolf tail
dog ears: dog ears
dog tail: dog tail
rabbit ears: rabbit ears
bunny ears: rabbit ears
rabbit tail: rabbit tail
bear ears: bear ears
horse ears: horse ears
horse tail: horse tail
mouse ears: mouse ears
animal ears: animal ears
tail: tail
fluffy tail: fluffy tail
elf ears: pointy ears
pointy ears: pointy ears
horns: horns
demon horns: demon horns
dragon horns: dragon horns
dragon tail: dragon tail
wings: wings
angel wings: angel wings
demon wings: demon wings
bat wings: bat wings
fairy wings: fairy wings
halo: halo
kitten: cat
puppy: dog
bunny: rabbit
furry: furry
anthro: furry
anthropomorphic: furry
alicorn: alicorn
pegasus: pegasus
unicorn: unicorn
koi: koi fish
# objects
smartphone: cellphone
phone: cellphone
flowers: flower
roses: rose
teacup: cup
bouquet: bouquet
umbrella: umbrella
katana: katana
sword: sword
# body
large breasts: large breasts
medium breasts: medium breasts
small breasts: small breasts
flat chest: flat chest
muscular: muscular
tall: tall
petite: petite
tanned: tan
pale skin: pale skin
dark skin: dark skin
freckles: freckles
makeup: makeup
lipstick: lipstick
# quality / filler words that Pony replaces with score tags: dropped but reported
highly detailed: 
ultra detailed: 
extremely detailed: 
very detailed: 
hyper detailed: 
hyperdetailed: 
intricate details: 
intricate: 
detailed: 
high detail: 
fine details: 
masterpiece: 
best quality: 
high quality: 
top quality: 
4k: 
8k: 
hd: 
uhd: 
high resolution: 
high res: 
sharp focus: 
professional: 
trending on artstation: 
artstation: 
pixiv: 
award winning: 
stunning: 
gorgeous: 
amazing: 
beautiful: 
breathtaking: 
incredible: 
epic: 
perfect anatomy: 
unreal engine: 
octane render: 
digital art: 
digital painting: 
concept art: 
illustration: 
wallpaper: 
very aesthetic: 
cinematic: 
"""

# --------------------------------------------------------------------------------------------
# Tokenizer
# --------------------------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-z0-9_]+|[,;.!?:\n]")
_SKIP = {"a", "an", "the", "her", "his", "their", "its", "my", "our"}
_BREAK = set(",;.!?:\n")
_LEADIN_RE = re.compile(
    r"\b(?:there (?:is|are)|(?:an? )?(?:image|picture|photo|photograph|illustration|render) of|"
    r"showing|featuring|depicting|shows|features)\b")


def tokenize(text: str) -> list[str]:
    text = text.lower().replace("’", "'")
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
        # "key: " where the value itself starts with ':' (":p" tag) is written ":: :p" - handled below
        if not val and line.endswith("::"):
            continue
        toks = tuple(t for t in tokenize(key) if t not in _BREAK)
        if toks:
            out[toks] = [v.strip() for v in val.split(",") if v.strip()]
    return out


PHRASES = _parse_table(_TABLE)
PHRASES[("tongue", "out")] = [":p"]  # tag starts with ':' so it can't live in the text table
_MAX_PHRASE = max(len(k) for k in PHRASES)

# --------------------------------------------------------------------------------------------
# Dynamic rules: colour + hair / eyes / garment
# --------------------------------------------------------------------------------------------
COLORS = {"black", "white", "red", "blue", "green", "yellow", "pink", "purple", "orange", "brown", "grey", "gray",
          "silver", "gold", "golden", "blonde", "blond", "navy", "cyan", "teal", "turquoise", "aqua", "crimson",
          "scarlet", "violet", "lavender", "magenta", "maroon", "beige", "cream", "ivory", "indigo", "platinum"}
COLOR_MODS = {"light", "dark", "pale", "deep", "bright"}
_NORM = {"gray": "grey", "blond": "blonde", "crimson": "red", "scarlet": "red", "violet": "purple",
         "navy": "dark blue", "golden": "gold"}
_HAIR_NORM = {"gold": "blonde", "yellow": "blonde", "platinum": "blonde", "lavender": "purple",
              "teal": "aqua", "turquoise": "aqua", "cyan": "aqua", "ivory": "white", "cream": "white"}

HAIR_MODS = {"long": "long hair", "short": "short hair", "medium": "medium hair", "wavy": "wavy hair",
             "curly": "curly hair", "straight": "straight hair", "messy": "messy hair", "spiky": "spiky hair",
             "fluffy": "fluffy hair", "shiny": "shiny hair", "braided": "braid", "silky": None, "flowing": None,
             "thick": None, "very": None, "colorful": "multicolored hair", "rainbow": "multicolored hair"}
EYE_MODS = {"glowing": "glowing eyes", "sparkling": "sparkling eyes", "bright": None, "big": None, "large": None,
            "beautiful": None, "deep": None, "piercing": None}
GARMENT_MODS = {"long": "long {g}", "short": "short {g}", "frilly": "frilled {g}", "ruffled": "frilled {g}",
                "pleated": "pleated {g}", "sleeveless": "sleeveless {g}", "lacy": "lace-trimmed {g}",
                "lace": "lace-trimmed {g}", "tight": None, "loose": None, "oversized": "oversized {g}",
                "elegant": None, "simple": None, "traditional": None}

_G = """dress kimono yukata hakama skirt miniskirt shirt blouse sweater hoodie jacket coat cape cloak scarf gloves
stockings pantyhose socks boots shoes sneakers hat cap beanie beret ribbon bow bowtie necktie tie bikini swimsuit
leotard bodysuit apron armor pants jeans shorts choker headband hairband crown tiara mask cardigan vest corset
sundress jumpsuit tuxedo suit uniform robe gown cheongsam qipao turtleneck bra panties lingerie garter belt
cat ears hair ribbon thighhighs kneehighs"""
GARMENTS = {tuple(w.split()): w for w in ("school uniform", "maid outfit", "tank top", "crop top", "sailor uniform",
                                          "t shirt", "thigh highs", "high heels", "witch hat", "sun hat")}
for _w in _G.replace("cat ears", "").replace("hair ribbon", "").split():
    GARMENTS[(_w,)] = _w
GARMENTS[("t", "shirt")] = "t-shirt"
GARMENTS[("thigh", "highs")] = "thighhighs"
GARMENTS[("sailor", "uniform")] = "serafuku"
GARMENTS[("maid", "outfit")] = "maid"
GARMENTS[("tank", "top")] = "tank top"
GARMENTS[("crop", "top")] = "crop top"
for _k in [k for k in GARMENTS if k == ("t", "shirt") or " ".join(k) == "t shirt"]:
    pass

_STOP = set("""with and in on at of to for by is are was were be being been it she he they them who that which this
these those while as from into onto over under near beside next wearing wears wear dressed has have having some
other another also then than there here up out just like about around through across against along toward towards
within without inside its it's one two their themselves herself himself or but if when where""".split())
_FILLER = set("""very really extremely super quite rather overall nice good great lovely perfect kind sort also style
scene image picture photo art artwork design look feel vibe atmosphere background setting environment shot view
angle pose composition quality overly slightly truly absolutely incredibly highly most more much well""".split())


def _colour(tokens, j):
    """Parse [mod] colour at j -> (end, name) or None."""
    n = len(tokens)
    if j >= n:
        return None
    mod = None
    if tokens[j] in COLOR_MODS and j + 1 < n and tokens[j + 1] in COLORS:
        mod, j = tokens[j], j + 1
    if tokens[j] in COLORS:
        base = _NORM.get(tokens[j], tokens[j])
        return j + 1, (f"{mod} {base}" if mod else base)
    return None


def _scan_attr(tokens, i, head, mods, kind):
    """[mods/colours]+ head  ->  tags, used for '<len> <colour> hair' and '<colour> eyes'."""
    n, j, tags = len(tokens), i, []
    while j < n and j - i < 8:
        t = tokens[j]
        c = _colour(tokens, j)
        if t in mods:
            if mods[t]:
                tags.append(mods[t])
            j += 1
        elif c:
            name = c[1]
            if kind == "hair":
                b = name.split()[-1]
                name = name.replace(b, _HAIR_NORM.get(b, b)) if b in _HAIR_NORM else name
            elif kind == "eyes":
                b = name.split()[-1]
                if b in ("teal", "turquoise", "cyan"):
                    name = name.replace(b, "aqua")
            tags.append(f"{name} {head}")
            j = c[0]
        elif t == "and" and tags and _colour(tokens, j + 1):
            j += 1
        else:
            break
    if j > i and j < n and tokens[j] == head:
        nxt = tokens[j + 1] if j + 1 < n else ""
        if head == "hair" and nxt in ("ribbon", "bow", "ornament", "clip", "band", "tie", "flower", "accessory"):
            return None
        return j + 1 - i, tags
    return None


def _scan_garment(tokens, i):
    n, j, mods, cols = len(tokens), i, [], []
    while j < n:
        t = tokens[j]
        c = _colour(tokens, j)
        if t in GARMENT_MODS and not cols:
            mods.append(t)
            j += 1
        elif c:
            cols.append(c[1])
            j = c[0]
        elif t == "and" and cols and _colour(tokens, j + 1):
            j += 1
        else:
            break
    for L in (2, 1):
        g = GARMENTS.get(tuple(tokens[j:j + L]))
        if g:
            tags = [GARMENT_MODS[m].format(g=g) for m in mods if GARMENT_MODS[m]]
            tags += [f"{c} {g}" for c in cols]
            if not cols and not any(GARMENT_MODS[m] for m in mods):
                tags.append(g)
            return j + L - i, tags
    return None


def _table_match(tokens, i):
    for L in range(min(_MAX_PHRASE, len(tokens) - i), 0, -1):
        key = tuple(tokens[i:i + L])
        if key in PHRASES:
            return L, PHRASES[key], " ".join(key)
    return None


def _clean_tag(t: str) -> str:
    if t.startswith(("score_", "source_", "rating_")):
        return t
    return t.replace("_", " ")


def _flush(pending, tags, dropped):
    """Leftover words that no rule claimed: adverbs/filler/lone colours are dropped, the rest
    becomes tags ('wooden bench', 'paper lantern'); long runs are split word by word."""
    words = [w for w in pending if w not in _FILLER]
    dropped.extend(w for w in pending if w in _FILLER)
    keep = []
    for w in words:
        if w.isdigit() or len(w) < 2 or (w.endswith("ly") and w not in ("lily", "holly")) or w in COLORS \
                and len(words) == 1:
            dropped.append(w)
        else:
            keep.append(w)
    if not keep:
        return
    if len(keep) <= 3:
        tags.append(_clean_tag(" ".join(keep)))
    else:
        tags.extend(_clean_tag(w) for w in keep)


def prose_to_tags(text: str) -> tuple[list[str], list[str]]:
    tokens = tokenize(text)
    tags: list[str] = []
    dropped: list[str] = []
    pending: list[str] = []
    i, n = 0, len(tokens)
    while i < n:
        t = tokens[i]
        if t in _BREAK:
            _flush(pending, tags, dropped), pending.clear()
            i += 1
            continue
        hit = (_scan_attr(tokens, i, "hair", HAIR_MODS, "hair") or _scan_attr(tokens, i, "eyes", EYE_MODS, "eyes")
               or _scan_garment(tokens, i))
        if hit:
            used, new = hit
            _flush(pending, tags, dropped), pending.clear()
            tags.extend(new)
            i += used
            continue
        m = _table_match(tokens, i)
        if m:
            used, new, phrase = m
            _flush(pending, tags, dropped), pending.clear()
            if new:
                tags.extend(new)
            else:
                dropped.append(phrase)
            i += used
            continue
        if t in _STOP:
            _flush(pending, tags, dropped), pending.clear()
        else:
            pending.append(t)
        i += 1
    _flush(pending, tags, dropped)
    return tags, dropped


# --------------------------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------------------------
_COUNT_RE = re.compile(r"^(\d+)(girl|boy|other)s?$")
_COUNT_WORDS = {"multiple girls", "multiple boys", "no humans"}


def _dedupe(tags):
    seen, out = set(), []
    for t in tags:
        k = t.lower()
        if t and k not in seen:
            seen.add(k)
            out.append(t)
    return out


def assemble(tags: list[str], source: str = "anime", rating: str = "safe") -> list[str]:
    """Order tags the Pony way: score, source, rating, character count (+solo), then the rest."""
    tags = [t.strip() for t in tags if t and t.strip()]
    body = [t for t in tags if not t.startswith(("score_", "source_", "rating_"))]
    counts = [t for t in body if _COUNT_RE.match(t) or t in _COUNT_WORDS]
    rest = [t for t in body if t not in counts and t != "solo"]
    people = sum(int(_COUNT_RE.match(c).group(1)) for c in counts if _COUNT_RE.match(c))
    multi = any(c.startswith("multiple") for c in counts)
    has_solo = "solo" in body
    solo = (people == 1 and not multi) or (has_solo and people <= 1 and not multi)
    head = list(SCORE_TAGS)
    if SOURCE_TAGS.get(source):
        head.append(SOURCE_TAGS[source])
    head.append(RATINGS.get(rating, "rating_safe"))
    return _dedupe(head + counts + (["solo"] if solo else []) + rest)


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


def translate(text: str, source: str = "anime", rating: str = "safe") -> dict:
    tags, dropped = prose_to_tags(text)
    final = assemble(tags, source, rating)
    return {"prompt": ", ".join(final), "negative": suggest_negative(source, rating, final),
            "tags": final, "dropped": _dedupe(dropped)}


def normalise_tag_list(text: str, source: str = "anime", rating: str = "safe") -> dict:
    """Post-process an already comma-separated tag list (e.g. LLM output) the same way."""
    text = re.sub(r"^```\w*|```$", "", text.strip(), flags=re.M)
    raw = [re.sub(r"\s+", " ", p.strip().strip("\"'.").lower()) for p in re.split(r"[,\n]", text)]
    tags = [_clean_tag(p) for p in raw if p]
    final = assemble(tags, source, rating)
    return {"prompt": ", ".join(final), "negative": suggest_negative(source, rating, final),
            "tags": final, "dropped": []}


if __name__ == "__main__":
    assert len(PHRASES) >= 150, len(PHRASES)
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
    assert r["tags"].index("1girl") < r["tags"].index("long hair")
    assert "highly detailed" in r["dropped"]
    two = translate("two girls and a cat sitting on a wooden bench, blue sky, wearing red dresses", "cartoon")
    assert "2girls" in two["tags"] and "solo" not in two["tags"] and "wooden bench" in two["tags"], two["tags"]
    assert "cat" in two["tags"] and "red dress" in two["tags"] or "red dresses" in two["tags"], two["tags"]
    man = translate("a man alone at night in a forest, photorealistic", "realistic", "questionable")
    assert man["tags"][3] == "rating_questionable" and "1boy" in man["tags"] and "night" in man["tags"], man["tags"]
    assert "source_anime" not in man["tags"] and "realistic" in man["tags"]
    print("pony self-test: ok (%d phrases)" % len(PHRASES))
