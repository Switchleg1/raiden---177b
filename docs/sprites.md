# Sprite system

Same philosophy as the terrain: **art is produced once and shipped as PNG;
gameplay only loads files.** Character art goes one step further — one still
per design is keyed, cropped and then *animated by code*, so the shipped
sheet's motion (core pulse, engine flare, roll, hull bob) is procedural.
Vector drawing remains everywhere as a graceful fallback, so the game still
runs from a bare checkout with no baked art at all.

## Layout

```
src/sprites/     sheet_table.py (the SPRITES records) + manifest.py (path and
                 grid helpers) + rawkit.py + fxkit.py + painters.py + bank.py
                 + anim.py  (pygame, lazy-safe; __init__ re-exports the API)
assets/textures/sprites_raw/<stem>[@RxC].png
                 generated stills / strips (source only, never shipped)
scripts/bake_sprite_raws.py  raws -> assets/textures/sprites_src/ + manifest_src.json
                             (bake-time keyed art; never copied into a build)
scripts/bake_sprites.py      manifest -> data/textures/sprites/  (raws + painters)
scripts/preview_sprites.py   contact sheet of any shipped sheet
scripts/preview_entities.py  boss + enemy roster over each sector's terrain
scripts/preview_fx.py        shots / whip / explosions over real terrain, at scale
scripts/preview_bosses.py    every boss mid-fight, and the bullet pattern each habit
                             actually throws (10 s footprint per sector)
assets/textures/sprites_src/<stem>.png  keyed sources (bake input, never shipped)
data/textures/sprites/<name>.png       shipped animated sheets
```

Override the art root with `RAIDEN_TEXTURE_DIR` (same env var as terrain).

## Generated raws → keyed sources → animated sheets

`assets/textures/sprites_raw/` holds one PNG per design. Naming:

- `e_gunner.png` — one subject per image (bosses: one subject per 3:2 frame).
- `e_grunt@4x2.png` — `@rowsxcols` strip, if the generator produced a grid.
- stems starting with `_` are notes/sidecars and are ignored.
- Background is either real alpha or flat magenta `rgb(255, 0, 255)`; both are
  accepted and normalised.

`scripts/bake_sprite_raws.py` turns each raw into a keyed square-ish source in
`assets/textures/sprites_src/` (long edge `SRC_PX = 384`, 4× supersampled):

1. **key** — alpha, or magenta distance with a despill pass so the fringe does
   not stay pink;
2. **keep mask** — largest connected component + filled holes, which drops the
   generator's backdrop props, contact shadows and stray debris;
3. **crop** — bounding box of what survived, plus an even transparent margin;
4. **scale, then defringe** — downscale first (the scale itself creates the
   soft rim), then erode the semi-transparent ring and recolour what is left
   from the solid hull outward. Generated PNGs feather their silhouette against
   a black matte, and un-treated that matte reads as a dark halo in game.

Every source is measured (`rim_lum` before/after, coverage) into
`manifest_src.json`, and `SPRITES[name]["raw"]` records the stem. Sprites are
then *authored* against the sector they fight over — a pale or dark hull is
judged over a scrolled render of that map, never in isolation — because
contrast is fixed at the art, not in the renderer or the terrain palette (the
Options "high contrast" outline is the accessibility fallback).
If a raw is missing or unreadable, `bake_sprites.py` falls back to the
procedural painter for that sheet — the game looks coarser, never broken.

Batched raws are supported: `e_bomber+e_splitter+e_rammer@3x1.png` is one
generated strip whose three cells bake out to three separately keyed sources.
`e_shard` deliberately reuses `raw = "e_splitter"` at a 32×32 cell — a fragment
should look like a chip of its parent, and re-keying the same source at a
smaller size is cheaper and more consistent than drawing something new.

### The hero ship: one still, ten poses

`p_ship` is raw-backed but does **not** go through the generic enemy rig.
A generator cannot express "the same craft banking 16° left", so
`rawkit.build_player_sheet()` takes the keyed master still and derives the whole
sheet: pose 0/1 are the hover pair (engine pulse), then four bank poses
(soft/hard × left/right) built with `angle = -sign · level · 8°` plus
`xs = 1 - 0.045 · level` horizontal foreshortening, each in two plume states.
The recipe is `_PLAYER_TILES`; `build_sheet()` routes to it when a profile sets
`player = True`. Because every tile comes from the same pixels, the bank looks
like one craft turning rather than four different drawings.

### Anchors and motion

`src/sprites/rawkit.py` paints a cell from a keyed source plus **anchors** —
features named in fractions of the source bbox, so they stay correct at any
cell size:

| key     | shape                | meaning                                        |
| ------- | -------------------- | ---------------------------------------------- |
| `glow`  | `(x, y, r, amp)`     | power-core halo that breathes with the anim     |
| `plume` | `(x, y, w, lmin, lmax)` | engine exhaust, a flame wedge pointing up    |
| `spin`  | `(x, y, r, blades)`  | specular disc / iris rotating around the core   |
| `flap`  | float                | horizontal squeeze of the hull (wing beat)      |
| `bob`   | float                | vertical hull travel per frame, in pixels       |

Anchors are hand-placed in `rawkit.ANCHORS` (the six recurring enemy designs
were eyeballed against marked-up previews). **Bosses are auto-rigged**:
`_auto_boss_anchors()` finds the brightest, most saturated, most central
region of the art — the power core every Raiden-style boss exposes — and drives
a glow breath, a 4-blade iris swirl and a slow hull bob from it. Exhaust
plumes are deliberately skipped on bosses: the art already paints engine
smoke, and a synthetic flame at that scale reads as a bright nub.

Paint order per cell: hull → swirl → plumes → glow, then the anim's per-frame
transform. Determinism comes from `zlib.crc32` seeds (never `hash()`), and
frames are resized with `smoothscale` on a cyclic surface so wrapping anims
loop without a seam.

Big hulls are flashed differently from small ones: an enemy over
`BOSS_FLASH_RADIUS` keeps its art and gets a white wash on top, because the
silhouette trick that makes a grunt pop turns a boss that is being shot
continuously into a blank card.

### Per-sector bosses

`LevelSpec.boss` names the sheet (`e_boss1` … `e_boss9`, 208×144 cells);
`Game._spawn_boss` copies it onto `Enemy.sheet` and the renderer prefers
`e.sheet` over `ENEMY_SHEET[kind]` (which maps a bare `BOSS` to `e_boss1` —
there is no generic boss sheet any more). Collision still uses the entity radius
(`ENEMY_STATS[EnemyKind.BOSS].r = 56.0`, deliberately smaller than the art), so
a boss can be visually huge without being impossible to dodge, and
`EXPLOSION_TIER` keeps the boss-sized death blast. Each boss is checked over a
scrolled render of its own sector (`scripts/preview_entities.py`).

### Shield bubble

The shield is the only effect that lives *around* the player, which makes it the
easiest effect in the game to draw wrong: a bubble painted over the craft hides
the thing it protects, so both the art and the draw order are load-bearing.

It is **baked wider than the hero** — 128×128 cells against the ship's 64×72, so
the silhouette lands outside the airframe at every angle — and it is **blitted
before the hull**, never after. Its shell is six gapped plates (a solid ring
would hide the craft and its spin would be invisible), with a faint interior wash
that brightens into the flare when a hostile bullet is near, and a deploy pop of
its own: the ring sweeps out from the craft in nine frames, sized so the window
`SHIELD_DEPLOY_TIME` is exactly `len(deploy frames) / fps` — the constant is
derived from the manifest, so retiming the art retimes the effect.

Because the effect must never lie about the model, everything it shows is derived
from `7.0 - Player.shield` and the bullet list the renderer was handed: no RNG,
no stored state, no mutation.

## Sheet table

`SPRITES` (in `src/sprites/sheet_table.py`, data only — no logic) is a dict of
sheet name → `{cell: (w, h), anims: {...}}`, and `manifest.py` is the small
helper layer over it (`sheet_path`, `cols_for`, `tile_count`, `raw_stem`). A
sheet is a plain grid: frames laid out left-to-right, top-to-bottom, max 8
columns (`tile_xy()` is the single addressing function — tests round-trip it). The
**first** declared anim fixes the tile count / column layout (it may double
as a demo cycle); later anims index into that same grid.

| sheet                | cell    | content                                    |
| -------------------- | ------- | ------------------------------------------ |
| `p_ship`             | 64×72   | raw hero, 10 frames — hover pair + 4 banks × 2 engine states (see above) |
| `e_grunt` `e_weaver` `e_darter` `e_gunner` `e_sentry` `e_heavy` | 44–84 | 6 enemy designs, 4–8 frame idle (glow pulse, plume, bob/flap) |
| `e_bomber`           | 96×84   | shell carrier: 6 frame bay pulse            |
| `e_splitter`         | 64×64   | 6 frame membrane breathe                    |
| `e_rammer`           | 56×72   | 4 frame intake flare (charges, never fires)  |
| `e_shard`            | 32×32   | splitter raw re-keyed small: 4 frames        |
| `e_boss1` … `e_boss9`| 208×144 | one boss per sector: core breath, iris swirl, hull bob |
| `shot_vulcan`        | 12×16   | 4-frame amber tracer bolt                   |
| `shot_plasma`        | 16×24   | violet beaded orb (Vulcan ≥ level 4)         |
| `shot_missile`       | 14×22   | finned airframe, lit/shadow flank, two-tone exhaust |
| `shot_moon`          | 26×26   | 4-frame spinning crescent (the piercing blade) |
| `shot_enemy`         | 12×12   | orange orb, rippling counter-rotating rim    |
| `fx_whip`            | 26×26   | magenta bead whose glow reaches `WHIP_BEAD_R` |
| `fx_shield`          | 128×128 | 21 frames: 12-turn spin + 9 deploy pop — a bubble that wraps the hull |
| `items`              | 28×28   | 10 pickup pods × 4 frames, one anim per kind (see below) |
| `fx_item_aura`       | 36×36   | `orbit`, 12 frames @ 9 fps — one shared marker, tinted per kind |
| `explosion_small`    | 48×48   | 8 frames @ 22 fps                           |
| `explosion_mid`      | 80×80   | 12 frames @ 20 fps                          |
| `explosion_big`      | 160×160 | 16 frames @ 18 fps (bosses, player death)  |

Animation metadata (`Anim`): frame-sequence name → `frames` (tile indices —
sequences may ping-pong), `fps`, `loop`. `Anim.tick(dt)` advances a float
playhead; `tile_index()` resolves it; `done` flags finished one-shots.

## Player banking

The baked art lives in 64×72 cells but blits at `PLAYER_SPRITE_SCALE`
(display-only; cached per tile, hitbox untouched) so the hero stays
proportionate next to the 32–84 px enemy sprites.

`p_ship` bakes the straight craft once at 3× supersample, then produces bank
frames with the classic 2D lean trick: `rotozoom` by ±8°/±16° plus a slight
horizontal squash for foreshortening (left mirrors right). Tiles are two
engine-pulse frames (A/B plume length) per pose. The renderer derives a
smoothed horizontal velocity from the craft's per-frame `x` (input-agnostic —
keyboard and mouse both just move it) and selects `idle` / `bank_soft` /
`bank_hard` (and `_l` variants) by the thresholds `PLAYER_BANK_SOFT` /
`PLAYER_BANK_HARD`.

## Float compositor (`fxkit.py`)

Bullets, the whip bead and every explosion are painted with `Tile`, a
premultiplied float RGBA buffer, rather than with `pygame.draw` calls. The
reason is empirical: `pygame.draw.circle` on an `SRCALPHA` surface **replaces**
the destination alpha instead of compositing it, so stacking two translucent
shapes gives the top shape's alpha and no bloom — glows either vanished or
baked visible square edges.

- `Tile(w, h, ss=)` keeps float colour (0–255) and alpha (0–1) at a supersample
  factor, then `surface()` box-filters down once and straightens the
  premultiplication. One downscale, so thin highlights survive.
- Primitives: `disc` (with `wobble=(lobes, phase, amp)` rim ripple), `capsule`,
  `box`, `cone`, `tri`, `annulus`, `bloom` (polynomial falloff), each taking
  `alpha=` and compositing source-over.
- `window(radius, edge)` multiplies alpha by a radial smoothstep. Anything
  radial ends with this, which is what stops a bloom from ending in a square.

## Explosions

Each tier paints one continuous event across its frames, driven by normalized
progress `p = i/(n-1)`. The same seeded lobe set is reused for every frame, so
a burst reads as one object expanding instead of noise re-rolled per frame:

1. **flash** (`p < 0.2`) — six `_wedge()` spikes (three stacked passes each, so
   the root is white-hot and the tip fades) over a warm bloom and a growing core;
2. **fireball** — a wobbling cool rim disc behind a wobbling hot body, churned
   rim lobes (angle drifts with `q`, alternating per lobe), cooler burn pockets,
   and a white core that shrinks and dissolves;
3. **breakup** — an ash core of cooling fire while the lobes fly outward;
4. **smoke and embers** (`p ≥ 0.8`) — grey puffs plus a few surviving sparks,
   alpha to 0 on the last frame.

Everything is clamped inside the cell's inscribed circle
(`dist = min(dist, rmax - lr)` then `window(rmax)`): a fireball that grazed the
cell edge used to stamp a square of orange onto the terrain.

`Effects.add_explosion(x, y, tier)` spawns a playhead; the renderer blits the
current tile centered. `EXPLOSION_TIER` maps enemy kinds → tier (boss and
player death = big; bomber/splitter = mid, rammer/shard = small). Particle
sparks remain on top for debris — sprite + vector together, like the original's
layered blows.

Determinism: painters seed all randomness from `_rng_for(sheet)`, which uses
**`zlib.crc32`, not Python's `hash()`** (process-randomized — would break the
stale-art detector and make bakes irreproducible across runs).

## Bank & hit-flash

`Bank` loads each sheet PNG once (`convert_alpha`), returns tile sub-surfaces
via `frame()`, and `white(sheet, tile)` builds the hit-flash silhouette: a
copy filled with `BLEND_RGB_MAX` — RGB → 255 while the alpha mask is
untouched, so the sprite flashes white in its exact shape. Enemies flash for
`flash = 0.12 s` after taking whip/collision damage.

`tinted(sheet, colour)` is the mirror image of that trick: a copy filled with
`BLEND_RGB_MULT`, which recolours RGB while leaving alpha alone. The result is
cached per `(sheet, colour)`, so baking **one** neutral sprite and tinting it
nine ways costs one sheet on disk and nine surfaces in RAM.

## Whip weapon

Pickup `ItemKind.WHIP` (weighted like other rare items) sets
`Game.whip_timer` (~12 s). While active:

- the Vulcan is **replaced** by the lash (no bullets — Raiden's
  Strike-Weapon tradeoff: aggressive damage for losing range),
- `entities.Whip` models it as `WHIP_POINTS` (18) points along a 300 px lash,
  rippled by a traveling sine (`WHIP_WAVE_*`) for the crackling snake look,
- **it leans where the lean is put**: the shape is `aim * f ** WHIP_CURL_POWER`,
  so the handle stays where the craft points and the outer section hooks over.
  A linear lean is a rod tilting on a pivot; a power above one is a curl, and
  the wave tapers the same way (`WHIP_WAVE_TAPER`) so the crackle lives at the
  tip instead of shaking the handle,
- **it looks for work**: `Game._whip_target()` offers the nearest live hostile
  inside `WHIP_SEEK_RANGE` and the lash steers onto its *bearing* — the anchor,
  the handle and the hostile collinear — at `WHIP_AIM_RATE` radians a second.
  Slewing rather than snapping is the balance: a whip that arrived at a target
  in one frame would be a homing missile wearing a rope, and undodgeable. With
  nothing in range it falls back to the `WHIP_SWEEP_HZ` side-to-side sweep, and
  a hostile **below** the craft is refused, because the lash is anchored above
  the cockpit and folding it back through the hull cuts nothing but the
  player's own silhouette. The choice is made by position and list order and
  never by RNG, so a seeded replay reproduces every swing,
- contact damage: `WHIP_DMG` per enemy per `WHIP_HIT_CD` seconds
  (`Game._whip_cd`),
- rendering: one `fx_whip` bead per point (pulsing scale) over a two-pass
  magenta polyline glow; if the sheet is missing the beads are circles.

All whip constants live in `config.py` (`WHIP_*`), the simulation is
pygame-free and covered by `tests/test_sprites.py` (attachment, expiry,
forward reach, arc bounds, the reach the length is supposed to buy, curl
measured against the same lash with the power set to 1.0, bearing-lock onto a
target, the slew limit, the refused target below the craft, the sweep that
resumes with nothing to chase, and the game-side choice of nearest reachable
hostile).

## Half-moon blades

Pickup `ItemKind.MOON` raises a **third power track** (`Player.moon_level`,
`MOON_MAX_LEVEL = 4`): the craft throws a fan of crescents on `MOON_INTERVAL`,
automatically, next to the Vulcan and the missiles rather than instead of them.
The tracks are independent — a crescent never changes gun spread or missile
count — and, like every other power, the track is lost with the craft.

The blade is the only bullet that does not stop. `Bullet.pierce` survives its
own hit and keeps flying, remembering the hulls it has opened so a blade sitting
on a boss charges for it once and not once per frame. That memory is held **by
object identity, never by `id()`**: the deaths a blade causes free the very id it
would later mistake for a hull it has already cut, and a new grunt wearing a dead
grunt's number would be cut nothing. Ordinary shots allocate no memory at all
(`Bullet.cut is None`), so the common case never pays for the rare one.

The balance is the design, and `tests/test_moon_weapon.py` guards it: `MOON_DMG`
is one shell's damage, `MOON_SPEED` is below every shell, `MOON_INTERVAL` is
slower than the Vulcan's trigger. Not stopping is the whole advantage; if any of
the other three ever grows, the weapon stops being a trade.

Art (`_paint_shot_moon`, 26×26, 4 frames): a crescent is four concentric arcs
whose angular windows shrink inwards. The silhouette is the **outermost** arc —
the sharpened convex edge, and the two points it tapers to — and because each
inner arc covers less of the circle, the band closes to a point by itself. A
punched hole leaves a jagged inner edge at this size, and a constant-width
tapered arc gives a blade with no edge on it. `Tile.arc` takes a centre angle and
a **half**-angle, which is why the spans below look small. The frames turn the
blade a quarter turn each about its own middle — the arcs are drawn about a
centre pulled back along the spin axis, because a crescent's mass sits opposite
its arc centre — so a fan reads as spinning steel instead of wobbling. Colour is
cold steel over a cyan bloom: the palest projectile in the game, which is what
keeps it readable over green fields and city glass. The pod glyph is the same
construction at 28 px, and the HUD pip is two plain arcs, because the HUD line is
15 px and a 26 px tile blitted into it droops out of the strip.

## Item pods and the shared orbiting marker

Pickups are drawn as two layers: a **pod** (`items`, per kind) and an
**aura** (`fx_item_aura`, one shared sheet recoloured per kind). Both come out
of the float compositor, because the marker has to be translucent over terrain
and the pod has to keep a hard silhouette at 20 px.

**Pod** (`_pod_shell`, six stacked passes): drop thickness → dark casing →
accent-glow rim → hull → lit upper face → recessed window with accent bloom,
glass-edge annulus and four rivets. The accent-bright rim between two dark
plates is what keeps a pod separable from dark ground; at 20 px it is
*structure* (bevel, recess, rivet) rather than texture that reads. Hazards get
an **octagonal** plate — "do not touch" has to be a shape, not only a colour —
painted by `disc(wobble=(8, tau/16, 0.048))`; larger wobble amplitudes turn the
plate organic and swallow the symbol. `_item_symbol()` then draws the glyph per
kind and animates it (arrow bob, missile flame length, bomb spark blink, medal
star pulse, …), and `_paint_items()` adds a specular sweep travelling across
the casing, which is why all four frames differ.

Symbols are chosen for legibility, not realism: a single up-arrow for weapon
two stacked chevrons read as a tree), a heraldic disc-over-triangle for shield
(a hexagon with bars reads as a speaker grille). Bright glyphs always draw a
dark enlarged copy behind themselves first, or the bloom merges them into a
blob.

**Aura** (`_paint_fx_item_aura`) is one neutral white sprite: a breathing
bloom, a faint full ring, three solid swept comet blades, two counter-rotating
gauge ticks, and a centre punched transparent with `t.hole()` so the marker
frames the pod instead of veiling it. Blades are arcs, not triangles — a
straight triangle ignores the ring's curvature and bakes into a dashed ring —
with a wide fading tail behind a short hard-edged head, ~115° each so three of
them never merge into a solid ring and the spin disappears. Drawn *behind* the
icon, so the blades emerge from under the hull.

Nine colours, one asset: the renderer takes the kind's accent from
`ITEM_AURA_TINTS` and blits `bank.tinted("fx_item_aura", accent)`. Pod accent,
aura tint and the high-contrast vector colour all read from a single palette,
`ITEM_COLORS` in `config/item_rules.py`, and a test asserts they agree.

The aura is deliberately wider than the hitbox (`ITEM_SIZE = 20`, aura ≈35 px):
the **pod** is what you have to touch, the marker is what you notice falling.
Each item carries a `phase` (0–1) so a cluster of five does not pulse in
lockstep; it is quantised from the spawn position rather than drawn from the
game RNG, because a renderer detail must not shift the simulation's stream.

## Workflow

```sh
python scripts/bake_sprite_raws.py     # stills -> keyed sources (only if raws changed)
python scripts/bake_sprites.py         # repaint all sheets from raws + painters
python scripts/preview_sprites.py e_boss3 e_heavy   # frame contact sheet
python scripts/preview_entities.py     # boss + roster over every sector, in-engine
python scripts/preview_fx.py --only shots --scale 2   # bullets over real ground
python scripts/preview_fx.py --only items --scale 1.3 # pods + aura over real ground
python -m pytest tests/test_sprites.py # determinism + stale-art + whip model
```

`scripts/build.py` refuses to package when any manifest sheet or scheduled
terrain map is missing.

## Adding an enemy

1. Drop the still in `assets/textures/sprites_raw/` as `<stem>.png` (solid or
   magenta background, subject roughly centred, nothing else in frame).
2. Add `"<sheet>": {"cell": (w, h), "anims": {...}}` to
   `src/sprites/sheet_table.py` and set `raw = "<stem>"` — plus, for a new
   recurring design, an entry in `rawkit.ANCHORS` (see
   `scripts/preview_sprites.py --anchors <stem>` for a marked-up source to
   pick fractions from).
3. `python scripts/bake_sprite_raws.py && python scripts/bake_sprites.py`.
4. Check it in context with `scripts/preview_entities.py --levels <n>`. If it
   reads muddy, re-author the still (or nudge `SRC_PX` / the mask thresholds in
   `bake_sprite_raws.py`) — do not brighten the terrain to compensate, and do
   not add a renderer outline: those hide the problem instead of fixing it.
