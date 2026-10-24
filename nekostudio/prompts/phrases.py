"""Prose phrase table: \"phrase: tag, tag\". Empty right side = drop and report. Every tag is
validated against the tag dictionary at runtime, so a wrong entry here can only be dropped, never emitted."""
TABLE = """
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
witch: witch
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

# ---- additions for the dictionary-backed matcher (validated against tagdb at runtime) ----
leaping: jumping, midair
leaps: jumping, midair
leap: jumping, midair
mid air: midair
low angle: from below
dramatic low angle: from below
worm eye view: from below
high angle: from above
overhead view: from above
overhead: from above
birds eye view: from above
mist: fog
misty: fog
foggy: fog
curled up: 
sipping: drinking
latte: coffee, cup
espresso: coffee, cup
coffee: coffee, cup
sunlit: sunlight
golden hour: sunset
sunglasses pushed up on head: eyewear on head, sunglasses
sunglasses on head: eyewear on head, sunglasses
lounging: reclining
chrome arm: mechanical arms
metal arm: mechanical arms
robotic arm: mechanical arms
cybernetic arm: mechanical arms
neon signs: neon lights
neon sign: neon lights
neon: neon lights
sharing umbrella: shared umbrella, umbrella
share umbrella: shared umbrella, umbrella
sailor school uniform: serafuku, school uniform
sailor school uniforms: serafuku, school uniform
sailor uniform: serafuku, school uniform
sailor uniforms: serafuku, school uniform
pastel colors: pastel colors
elven: elf, pointy ears
elf: elf, pointy ears
elves: elf, pointy ears
plate armor: plate armor, armor
silver plate armor: plate armor, armor, silver armor
ornate silver plate armor: plate armor, armor, silver armor
asleep: sleeping
sleeping: sleeping
sleeps: sleeping
oversized hoodie: hoodie, oversized clothes
oversized sweater: sweater, oversized clothes
oversized shirt: shirt, oversized clothes
oversized jacket: jacket, oversized clothes
oversized armchair: armchair
playing video games: video game, playing games
video games: video game
late at night: night, dark
at night: night
night time: night
nighttime: night
on bed: on bed
sitting on bed: sitting, on bed
room: indoors
monitor glow: monitor
glowing monitor: monitor
raining: rain
rainy: rain
rain soaked: rain
rain streaks down window: rain, window
rainy street: rain, street
snowing: snow
snowy: snow
windy: wind
blowing in wind: wind
billowing: wind
cozy: 
cinematic: 
dynamic: 
dramatic: 
warm: 
soft: 
tall: 
ancient: 
glowing blue sword: glowing sword, holding sword, sword
holding sword: holding sword
katana drawn: katana, holding sword
sword drawn: sword, holding sword
drawn katana: katana, holding sword
drawn sword: sword, holding sword
unsheathed katana: katana, holding sword, unsheathed
wielding sword: holding sword
wielding katana: katana, holding sword
anthropomorphic: anthro
anthropomorphic fox: anthro, fox
anthropomorphic wolf: anthro, wolf
anthropomorphic cat: anthro, cat
furry: furry
wolf boy: 1boy, wolf ears, wolf tail
fox boy: 1boy, fox ears, fox tail
cat boy: 1boy, cat ears, cat tail
anthro fox girl: 1girl, fox ears, fox tail, fox girl
anthropomorphic fox girl: 1girl, anthro, fox ears, fox tail, fox girl
anthropomorphic wolf boy: 1boy, anthro, wolf ears, wolf tail
barista: barista
chibi: chibi
teenage: 
potion bottles: potion, bottle
potion bottle: potion, bottle
leather bound: 
leather bound spellbook: spellbook
ancient leather bound spellbook: spellbook, book
reading book: reading, book
reading spellbook: reading, spellbook, book
spellbook: spellbook, book
crackling fireplace: fireplace, fire
crackling fire: fire
by fireplace: fireplace
warm golden light: sunlight
golden light: sunlight
warm light: sunlight
golden hour lighting: sunset
soft shadows: shadow
pile of gold coins: gold, coin
gold coins: gold, coin
treasure chests: treasure chest
treasure chest: treasure chest
puffs of smoke: smoke
little puffs smoke: smoke
smoke: smoke
gems: gem
gem: gem
cave: cave
dark cave: cave, dark
snack wrappers: 
wrappers: 
infinity pool: pool
luxury villa: 
villa: 
overlooking ocean: ocean
overlooking: 
ocean: ocean
cocktail: cocktail, cup
sipping cocktail: cocktail, drinking, holding cup
white bikini: white bikini
bikini: bikini
cityscape: city
city: city
rooftop: rooftop
rooftops: rooftop
between rooftops: rooftop
jumping between rooftops: jumping, midair, rooftop
cyberpunk: cyberpunk
mercenary: 
mercenary woman: 1girl
long coat: long coat
coat: coat
fox ears: fox ears
armchair: armchair
curled: 
lap: 
"""
