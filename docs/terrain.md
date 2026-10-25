# Terrain maps (`terrain/`)

Procedurally painted, vertically scrolling backdrop per sector — homage to
Raiden's stage progression. The campaign runs **nine sectors over thirteen
themes** (countryside, farmland, swamp, city, ruins, glacier, volcanic,
ocean, airbase, industrial, wasteland, canyon, forest); every sector
switches between **two terrain phases** (e.g. Sector 1: countryside →
farmland, Sector 4: glacier → ocean), matching Raiden's mid-level
environment changes. View layer only: terrain never affects gameplay and
the model never imports it — adding a theme costs paint code and baked art,
never spawn/enemy logic.

## Phase schedule (`TerrainTrack`)

- `LevelSpec.phases` is a tuple of `ThemePhase(theme, weight)`; weights
  normalise into the sector's own virtual-scroll timeline: `plan_span(level)`
  is the level's `wave_seconds` (so zones keep trading until the boss arrives,
  instead of the ground freezing on the last zone for half a long sector).
  `PHASE_PLAN = 46 s` is the fallback for a spec with no wave length.
- `TerrainTrack(phases, seed, maps=None, plan=PHASE_PLAN)` builds one `Terrain`
  per zone (same seed) — or adopts a prebuilt `maps` tuple from the prefetch
  cache, whose order must match `phases` exactly (the constructor refuses a
  mismatch). It advances a virtual clock `t += dt * speed_scale` — pausing
  freezes the
  schedule; the track is recreated in `_enter_ready()`, so sectors always
  replay identically.
- At each zone boundary the incoming zone is **revealed by a boundary that
  travels down the field**: `PHASE_SWEEP = TILE_H / NEAR_SPEED` (one
  field-height of ground travel), the outgoing zone drawn plain and the
  incoming zone painted over it through a 0/255 mask. There is no alpha
  ramp anywhere — an alpha ramp is the ground going translucent, and that is
  what read as "a fade shift in the middle of the level". Only the ~60 px band
  the boundary can reach is masked, so the whole operation costs ~0.8 ms and
  only during the handover.
- The boundary is a curve (`seam_y`: one broad swing plus a tighter fold, keyed
  to world position so the shape scrolls with the ground), not a straight clip:
  a perfectly straight cut "slices through scenery" and reads as a rendering
  glitch. Along it the ground gets a lit crest (2 px) and a cast foot (16 px),
  in colours sampled from the pixels already on the canvas — ground-appropriate
  by construction, and no props are stamped along the line (that reads as a
  boulder fence).
- All zones scroll every frame (offset arithmetic only — negligible cost),
  so a zone is always at a natural scroll position when its boundary arrives.
- Sector schedules: 1 countryside→farmland, 2 city→ruins, 3 ocean→airbase,
  4 ruins→canyon, 5 wasteland→canyon.
- Every (theme, seed) pair any sector schedules must have baked art; the
  bake script iterates the schedule (`level_art()`) and `build.py` refuses
  to package missing pairs.

## Structure

- **One `TerrainTrack` per sector**, built in
  `Renderer.set_terrain(level_spec, seed)` (called by the app in
  `_enter_ready()`; title screen clears it and falls back to the starfield).
  A `Terrain` is one baked map in three parts:
  1. `base` — static vertical gradient (theme-specific sky/ground tones),
     size 800×`TILE_H` (556 = playfield band height).
  2. `far` layer — distant silhouettes (tree lines, islets, towers, mesas),
     scrolls at `FAR_SPEED` 60 px/s.
  3. `near` layer — ground detail (fields/river, roads+blocks, wave streaks,
     wall fragments, cracks+rocks), scrolls at `NEAR_SPEED` 165 px/s.
- **Baked, not generated** (the important one): every gameplay map is
  painted OFFLINE by `scripts/bake_terrain.py` into
  `data/textures/terrain/<seed>_<theme>_{base,far,near}.png` at 2× (`SS`)
  resolution using LOGICAL coords (`_scale2`). At level start the
  `Terrain` constructor LOADS those three PNGs and downscales once —
  ~15 ms, no numpy needed at runtime, no loading screen.
  - Re-bake after ANY terrain art change: `python scripts/bake_terrain.py`
    (~4 s for all ten scheduled maps). Files are deterministic (seeded RNG).
  - `test_baked_matches_procedural` is the stale-bake detector: if painters
    and shipped PNGs drift, the suite fails and tells you to re-bake.
  - Procedural fallback: `terrain.build_procedural(theme, seed)` (~600 ms)
    runs only when baked art for a (theme, seed) is missing — tests, or
    hand-authored seeds. It composes from the generated tileset when
    `data/textures/tiles/` ships (see “Generated tileset” below), and from
    the vector painters otherwise. Never on the gameplay path for shipped
    levels.
  - `RAIDEN_TEXTURE_DIR` env var overrides the baked-art directory
    (`RAIDEN_TILE_DIR` does the same for the tileset).
- Layers are transparent `SRCALPHA` surfaces at logical size; scrolling
  draws each layer twice (`y = HUD_H + off` and `off - TILE_H`) for
  continuous wrap.
- `Terrain.draw(canvas)` sets a clip rect to `(0, HUD_H, 800, 556)` so the
  backdrop can never bleed into the HUD band (asserted in tests).

## Determinism

`_theme_rng(theme, seed)` seeds `random.Random` from `(seed, theme-index)`.
The app passes `seed = level_index + 1`, so **each sector always paints the
same map** across runs (matches the seeded-gameplay philosophy).

## Seamless vertical wrap rules

- Rect-ish primitives duplicate seam copies via `_ys(y, h)`; blobs via the
  `dy_offs` branch in `_blob`. Any shape crossing `y = 0`/`y = TILE_H` gets a
  copy offset by ∓`TILE_H` — never a hard cut at the seam.
- Rivers/dry riverbeds/bridges share `_river_x(step, rx, amp)` and use whole
  sine periods per tile — tile-periodic by construction, so bridges always
  land on the river and there are never seam artefacts.

## Generated tileset (`terrain/compose.py` + `terrain/tilekit.py` + `terrain/theme_table.py`)

The DEFAULT map source: `build_procedural` asks `compose.build_layers(theme,
rng)` first; the vector painters below remain the no-tileset fallback
(`tilekit.kit_available()` is a pure-filesystem check, safe pre-display).

- **Assets** (generated by the image pipeline, then prepped by
  `scripts/bake_tiles.py` into `data/textures/tiles/`):
  - `materials/` — 25 seamless 256px ground tiles: grass ×2, dirt road,
    mossy cobble, river/paddy water, concrete apron, cracked earth, ash,
    canyon sand, forest floor, gravel rubble, ocean, tarmac runway, asphalt,
    plus the new-theme set (marsh water, reed bed, mud flat, snow field, ice
    sheet, tundra moss, lava crust, obsidian, steel deck, rust plate). The
    prep pass measures an edge-mismatch ratio (seam error ÷ mean neighbour
    diff) and only runs the 25% crossfade repair when the ratio exceeds 1.6,
    so structured tiles (runway stripes, lane dashes) are never smeared.
  - `props/` — 18 top-down props chroma-keyed from magenta generations
    (tree/pine clumps, rock cluster, crate stack, red barn, house, lattice
    mast, dead tree, cypress clump, stilt hut, snow pine, ice boulder,
    basalt spire, lava vent, storage tank, long warehouse, cargo container,
    antenna dish) with despill + 1px alpha erosion.
  - `splats/` — 6 feathered edge blobs (dirt, grass, mud, scorch, snow, oil)
    used to melt hard boundaries. Edges are per-theme: `_road_v(edges=…)` /
    `_plaza(edge=…)` so a theme with no soil never gets dirt shoulders.
    Industrial uses `splat_oil` — pale dirt reads as field and the
    ember-flecked `splat_scorch` reads as fire, which the player takes for a
    hazard.
  - `manifest.json` — kind/px/metrics/sha1 per entry; `kit_available()`
    requires every listed file.
- **Composition** (all in a PERIODIC bake space of 1600×1120 — 10×7 grid
  of 160px tiles, 1120 = the wrap period):
  - base material fills every cell; alternates blit as **radially
    feathered masks** (smoothstep rim) so patch boundaries melt instead of
    drawing grid lines. **Materials are never flipped/rotated** — seam
    continuity only holds unflipped; props may flip/rotate freely.
  - roads/rivers/paddies/runways follow centre-lines that are sums of
    INTEGER-frequency sines (periodic by construction) and every stamp
    goes through `_blit_wrap` (drawn again ∓CH), so shapes crossing the
    seam continue exactly.
  - splats feather road/paddy/plaza edges; the whole near layer is then
    scaled to a per-theme arcade brightness mean (`theme_table.THEME_MEAN`,
    38–48, with
    glacier as the deliberate outlier at 86).
  - The finished period is stretched 1600×1120 → 800×556 by the normal
    bake path; stretching a full period preserves wrap continuity (seam
    row-difference measured at parity with ordinary row-to-row diffs).
- **Workflow:** regenerate assets → `python scripts/bake_tiles.py` →
  `python scripts/bake_terrain.py` → tests. `test_baked_matches_procedural`
  stays the stale-bake detector; the tileset is deterministic (seeded RNG,
  no `hash()`); `scripts/build.py` ships `data/textures/tiles/` alongside
  terrain/sprites.

## The site plan (`terrain/siteplan.py` + `terrain/features.py`)

Scattered props do not make a place. A landscape is **dependency-ordered**:
the ridges decide where water runs, water and ridges decide where the road
threads, the road decides where houses stand, the flat dry ground the road
left over is what gets enclosed, and the trees follow the water and the
treeline. `plan_site(theme, seed)` computes that chain as data; the painter
`terrain/features.py` only draws it.

- **Pure Python, no pygame, no numpy** — so the whole chain is testable
  headlessly (see `tests/test_terrain_siteplan.py`) and cheap (70–300 ms).
  The painter is where numpy lives.
- **Orogeny first.** Ridges are real cross-sections — sawback, domefield,
  mesa, cone, hogback, massif, ridge — each with a crest profile sampled
  along its spine, so a mesa has a table top with a cosine shoulder and a
  hogback has a scarp on one side and a dip slope on the other. The height
  field is then normalised to `SiteSpec.relief_gain`: the painter's colour
  ramp, rock coverage and snowline all key off `h` in 0..1, so an
  un-normalised plan paints a range at two thirds of its own contrast.
- **Drainage follows gravity**, then circulation *refuses* the two easy
  traps: a road that fights a ridge, and a road that runs with the river.
  The cost function rewards crossing water (a bridge is the most legible
  human object in a scrolling map) and penalises the share of the route
  hugging the channel — because low ground *is* the valley floor, and the
  valley floor is where the river already lives. Where a route does stand
  inside a channel band it gets decks: a short run one, a long run a
  causeway of decks ~110 px apart (`_decks`).
- **A grid city is planned as blocks.** Two mains (forced far enough apart
  to enclose a block), cross streets that leave room for the block they
  border, streets nudged off the river, and one parcel per cell of the
  grid. The layout then reads as the *gaps between* parcels, and streets
  that would otherwise run with the water stop doing that.
- **Nothing may contradict the ground it stands on**: houses only on flat
  dry ground with a road within reach and a drive to it, parcels only on
  ploughable ground and never swallowing the road, scree only at a ridge
  foot and never in a river, foliage never crowning a house or leaning over
  a channel.
- **Paint order = landscape order**: relief, water, parcels, roads, greens,
  buildings, cover. Painting the relief *over* fields and channels washes
  out both the cultivation and the elevation it was meant to explain.
- **Value is measured, not tasted.** `THEME_MEAN` forces a mean luminance,
  and a bare mean-match *scales*: a canyon forced to mean 46 ended with its
  entire value range compressed into lum 24–62, pale sand and gravel alike
  — that is what "everything shares one dark value range" is, arithmetically.
  So the targets were raised per theme (a desert is allowed to be bright)
  and `_darken` follows the mean-match with a stretch centred on the target
  mean: the mean is untouched, the spread comes back. Measured near-layer
  spread went from 39 (canyon) to 80.
- **Material choice is by measured luminance**, not by name: crop fields are
  brown earth (`road_dirt`, lum 105) and routes are grey gravel
  (`gravel_rubble`, lum 99) — same brightness, different hue, so "is that a
  field or a road?" stops being a question. Water gets a *band* of pale
  gravel/sand/snow under it rather than a stroked outline, because a stroke
  reads as drawn and a band reads as a shore.
- **Two themes stay hand-composed**: `ocean` (no ground to plan) and
  `airbase` (the runway is one specific object; a planned road network
  routes traffic through it). See `compose.PLANNED`.
- **What the review loop actually caught**, in order of cost: the road and
  the river sharing one corridor at every sample point; the tileset's
  "feathered patch" mask being a *square* (the grid tell); pygame thick
  lines having no round joins (the staircase tell); slope shading clipping
  to near-black on cliffs (the "rendering artefact" mesas); a NameError in
  the relief painter that `2>/dev/null` hid for several review rounds, so
  the reviewer was scoring stale PNGs. All of those are fixed, and the
  render scripts no longer swallow stderr.

## Streaming a sector (`Geom` + a windowed `Plane`)

The baked map is one screen tall: 1120 px, about 3.5 s of scroll. A 75 s sector
shows it end over end roughly twenty times, and the repeat is the reason the
mid-level zone change had to exist at all - a sector that never runs out of new
ground has no boundary to hide.

The groundwork is in, in two halves.

**Planning a strip.** `plan_site(theme, seed, geom)` takes a `Geom(w, h, cell,
cyclic)`; the default `Geom()` is the old one-screen map, so every existing
call site is unchanged. A streamed sector passes `Geom(h=21 * CH, cyclic=False)`
and gets a designed 21 screens, not one screen stretched: ridge trunks one to
two screens long, streets down the city's whole length at block spacing,
drainage every couple of screens, and path wander at *screen* scale even on a
long strip (a meander is something a player sees in one screen of flight). A
six-screen countryside strip plans in about 0.5 s - cheap enough to run once per
sector on the prefetch thread.

**Painting a window.** `Plane(w, h, x0, y0, wrap)` is a window of the world, not
the world. Masks, stamps and strokes come back in window coordinates, a feature
that misses the window costs nothing (`_raster` returns None), materials are
read phase-locked to world position (`_view`) so the tile grid cannot jump at a
chunk edge, and the relief field - the steepest flank, the usual steepness, the
height ramp - is measured once on the planning grid so that every window shades
with the same contrast. Jitter is keyed to the *feature* (`_frand(plan, index,
salt)`) rather than to the paint pass, which is what lets two windows paint the
same hedge identically.

**The open blocker, measured.** Two windows overlapping on the same world rows
still disagree on 0.05-2.9% of those pixels (max around 150/255), concentrated
within about one margin of the boundary. Painting with a ~96 px margin and a
chunk several tiles high drives it down; it does not remove it. Suspects, in the
order I would test them: `Mask._feather`'s box-edge `np.roll` (a mask clipped by
a window edge thickens differently there than the same mask unclipped), and
features whose *extent* reaches a window they are not anchored in (a tall tree
anchored a hundred-odd px below the kept band). Nothing streams at runtime until
that is closed, because a chunk boundary that changes a tree's edge is exactly
the tell the whole exercise is meant to remove.

**The camera convention, because it caused a bug.** `Level.near_y` is the strip
row standing at the *top* edge of the field, in bake px. It starts at one screen
(`TILE2`) so the opening band is full of ground on the first frame, it grows as
the craft flies forward, and so the picture moves *down* the screen - the same
direction the baked detail layers move. Getting this sign wrong is invisible in
a still and obvious in motion, so it is asserted: move the camera one slice,
the picture must move down by that much and must not stand still.

**Half of the throughput fix is in: the design pass runs in a process.**
`level/design.py` asks for a sector's plan in another interpreter, which has its
own GIL and gets its own core. The plan pickles *identically* across
interpreters - the planner keys its randomness on arithmetic and never iterates a
set - so a plan designed in a child is the plan designed here, which
`tests/test_level_design.py` asserts by comparing a plan's whole signature across
processes. A one-screen baked map stays in-process (the spawn costs more than the
design), and a refused or dead worker falls back to designing here, loudly.
`App.shutdown` dismisses the worker before the runtime comes down.

I wrote here that a site plan "is pure data - no numpy", and that was wrong in a
way that costs seconds: `SitePlan` carries four grid-wide arrays (`_w` plus the
ridge, water and built masks) which exist only while planning and are dead weight
afterwards. For a sector strip that is hundreds of megabytes going down a pipe on
every sector. Dropping them from `__getstate__` is the cheapest large win left,
and it is the reason the plan of ten screens measured 336 KB while a whole sector's
measured seconds.

**The streamed path is the default now, and the honest reason it still ramps.**
Measured, sector 1: **~8 s to design in the child** plus **~3 s to pickle it
back**, against a READY-plus-hold window of about 5 s. So the craft takes off
while its ground is still being invented, at 330 bake px/s, against a painter that
wants 0.75 s per 56 px slice - and spends the opening seconds outrunning both.
The first ten samples of a playtest read **0% ground**; the fights still arrive
from the ground (4 released in 10 s, model clock off), so everything is wired - it
is the schedule that is wrong. Sector 1 is the only sector like this: every later
one had the whole of the previous sector to prepare in. Three consequences, in the
order they are worth fixing: stop sending the scratch arrays over the pipe, start
the design at the title screen rather than at the run, and hold the launch on a
budget measured in *world distance travelled* rather than in wall seconds, so a
slow machine starts later rather than starting into an empty field.

**A number that misled me, and why.** With the design in a process but painting
still on threads, a run reported "1 slice of 66 in 8 s", which read as painting
starving. Partly true - but the bigger cause was that **a respawn was throwing
the sector's ground away**: `_use_level` built a fresh `Level` on re-entering the
sector, so the strip went back to row 0 under a craft standing halfway down it
and every finished slice was discarded. The baked path already guarded against
this (`ensure_terrain`); the streamed path had no equivalent. Fixed and asserted -
the sector being flown is kept, camera row and painted frontier included - and it
is worth stating plainly because a measurement that is *half* right sent me to
look in the wrong place for a while.

**The other half is in as well: slices are painted in the child too.** A slice is
0.75 s of numpy *and* pygame surface work, so on threads it still competed for
this interpreter's GIL; `level/paintsrv.py` asks the child to paint, and the
finished slice crosses as RGBA (about 0.9 MB after the child downscales it) to be
wrapped by the parent. The property this rests on is asserted before it is
trusted: the same slice painted here and there is the same picture - every pixel,
both layers, and the alpha channel, because an RGB-only comparison would pass a
slice that arrived translucent, which is a hole in the field wearing a smile.
The child caches the plan per sector and designs it single-flight, so two workers
never think up the same ground twice.

Measured after that change (same harness, sector 1, 20 s flown): painters sit
about three slices ahead of the camera.

**And then a bug I had written off as art turned out to be mine.** For several
measurements running, field coverage settled at **84.2%**, and I reported that
number as a ceiling imposed by the art - "local and streamed agree to the pixel,
so the missing 16% is the painter's business". The agreement was real and the
conclusion was wrong: both measurements went through the *same* `draw`, and that
`draw` passed the band rect as the blit's **area** argument. An area's left and
top are offsets *into the source surface*, so every slice lost FIELD_TOP rows off
its top and FIELD_LEFT columns off its left - 44 of every 280 logical rows,
236/280 = 84.3%, which is the number I called the art's fault. Play it: a bare
strip exactly the height of the toolbar at every slice boundary. Fixed, and the
same measurement now reads **100.0% opaque, 0 bare rows**. The lesson is not
"check the sign", it is that an agreement between two measurements that share a
bug is the most convincing kind of wrong.

So what is left visible is a **start-up ramp** - a sector entered cold spends its
first seconds inventing its own ground - and nothing else. In play this is paid
once, on sector 1, because the next sector has been painting since halfway
through this one.

**What is now known to be *not* wrong**, because each was suspected and then
measured: the surfaces that cross the boundary blit identically to local ones
(100% coverage either way); `Level.draw` and `TerrainStrip.draw` agree in-app;
and the camera convention, once fixed, holds across both paths.
Two of my own probes were invalidated by the spawn contract - a child re-runs an
unguarded entry script - so the rule here is that any measurement harness must be
imported-clean: module-level work under `if __name__ == "__main__"`, or the
child quietly runs the experiment too and the numbers mean nothing. A third was
invalidated by the crop above: it compared streamed drawing against local drawing
and concluded the ground was fine, when both were missing the same 44 rows.

**The blocker that mattered: threads are not enough, measured.** Flying a real
sector headless (`scripts/playtest_streamed.py`, sector 1,
12 s of 60 fps loop): the design pass had not finished after 12 s of wall clock,
and 1 slice of 66 was painted. Standalone the same design costs 2.7 s and a
slice costs 0.75 s, and the camera needs one slice every 1.7 s - so painting
alone wants roughly half a core, and a Python thread competing with the frame
thread for the GIL got about a fifth. The design pass is pure Python and never
releases the GIL at all; the painting releases it only where numpy or SDL do the
work. Two ways out, both real work:

- a **worker process** (the plan is pure data and pickles; slices come back as
  raw RGBA buffers, ~4 MB each, and the child needs a surface-free painter -
  `features.py` currently builds pygame surfaces), or
- a **smaller paint unit** at lower scale for the far layer, plus a cheaper near
  pass, so the budget per slice drops below what the frame thread leaves over.

The frame thread's own cost matters here too: a headless software blit is
~16 ms/frame and leaves almost nothing, while a hardware surface leaves more,
so this may be less hopeless in a real window than in a dummy driver. Measure
that before choosing. Until it is chosen, streaming stays off by default and
`--streamed-terrain` is a flag to try, not the way the game runs.

The plan when it is closed: chunk bank (LRU, 3-4 chunks) painted by the existing
prefetch worker, one continuous strip per sector, and `TerrainTrack`'s zones and
seam code deleted - the mid-level change becomes a change of land use along the
strip (roads, rivers and ridges carrying across it) rather than a boundary.

**The index that makes windows cheap, and what it costs to get wrong.** Culling
by y depends on every feature kind reporting the y-range it really occupies
(`_y_extent`). Ridges keep their points in `spine`, not `path`, and the helper
had no case for them: every ridge on a 20-screen strip was indexed at y 0..0.
In the baked one-screen path that is invisible - the window covers the whole
map, so "everything" and "everything at y 0" are the same set. In a strip it is
spectacular: the first slice got every ridge in the sector and every later slice
got none. `test_every_feature_kind_is_indexed_where_it_actually_is` is the guard,
and a new feature kind has to be findable by the index before it is painted.

**Design cost is now linear, and guarded.** Planning a strip used to answer
every spatial question - is this parcel off the road, does this drain stack on
the last one, does this route cross the river - by walking every segment of
every path, so cost grew with the square of the length: 28 s for a 111 s sector.
Path segments are now filed by the y-band they touch (cached per path object),
threshold queries stop at the first hit, and crossings test only segments
sharing a band. The same sector designs in about 2 s, and
`test_planning_a_strip_scales_with_its_length` fails if the shape goes
superlinear again. This is what makes an unprepared sector usable: the first
slice can be painted about two seconds after entering, not half a minute.

## Encounters come from the ground (`src/level/encounters.py`)

The spawn director has always worked on a clock: every `spawn_interval` seconds,
roll a kind and drop it over the top edge. That is why a sector stops feeling
like a place - the same formation can arrive over a rice paddy, a car park and a
lava channel, because nothing about the ground was consulted when it was placed.

A site plan already knows where the houses, water, steep flanks and open fields
are. Those are affordances, and the archetypes have homes:

| affordance | kinds | why the ground explains the shot |
|---|---|---|
| `roof`  | sentry, gunner    | a turret climbs out of the highest thing in view |
| `ridge` | heavy, rammer     | slow and armoured things come off high ground, on the flank perpendicular to the spine |
| `wet`   | splitter, bomber  | things that scatter rise off a wash |
| `open`  | grunt, weaver, darter | clear ground: not built, not wet, not on a crest |

`plan_encounters(plan, spec, tail=...)` walks the sector a beat at a time - one
beat per `spawn_interval` seconds of scroll, so density is still a level number
and has simply stopped being a clock - and for each beat draws a kind from the
sector's own roster, then asks the plan for a place that kind can stand. If the
ground has nothing to offer (no rooftop in this stretch), it says so rather than
inventing one in mid-air. Positions are in the plan's space, bake pixels down the
strip, which is the same y the painted strips are indexed by: the encounter and
the ground it belongs to are addressed identically.

Determinism holds: the draws are keyed on `plan.seed` and arithmetic over the
sector name, never `hash()`, so a replay meets the same guns in the same
doorways. Formations are decided with the site (a hamlet puts up a pair of guns,
a field puts up a file), and `LEAD_IN`/`LEAD_OUT` keep the sector from starting
or ending inside a formation. Not yet wired into `game.py`: the release path is
the next step, replacing the timer with "this ground is on screen".

## Realism layers

Three post/primitive passes give the maps a painted, non-flat look
(`numpy`-accelerated; every pass no-ops gracefully if numpy is missing):

1. **`_base_texture(base, rng, theme)`** — multi-octave value noise baked
   into the static gradient: 3 frequencies (blocky noise → 5-tap-blurred
   soft blobs) so ground has mottled patches, never flat fill. Ocean gets
   horizontally stretched octaves (current bands) instead of blotches.
2. **`_grain(surf, amp, rng)`** — ±4–5 per-pixel RGB grain applied to the
   2× painted layers *only where alpha > 0*, before `smoothscale` — every
   material gets texture; transparent pixels stay untouched so scaling
   produces no fringing.
3. **Shadow sheets** — each painter accumulates soft dark ellipses/rects
   (`_sh_ell` / `_sh_rect`, light from top-left) on a dedicated `SRCALPHA`
   sheet, blitted once at the end so overlapping shadows blend instead of
   double-replacing alpha. Trees, farms, buildings, cars, ships, oil rigs,
   towers, slabs, boulders, mesas and derricks all sit on the ground.

Other realism primitives: `_plot` (crop fields with jittered organic
outlines, hedge dots along the boundary, plough patches), `_foam_edge`
(broken surf line ringing islets), `_crest` (curved wave crests), `_wear`
(repair patches/stains on roads, decks, plots), lit/shaded faces on ruins
towers and mesas.

**Cost:** the passes run only at BAKE time. Gameplay pays ~15 ms per sector
(PNG load + one downscale) and imports no numpy at all.

## Detail vocabulary (Raiden motifs, all primitives)

`_tree_cluster` (canopy + shadow),
`_farm` (barn/silo compound), `_road_v`/`_road_h` (lane dashes + grain),
`_bridge`, `_river` (with dark banks), `_specks` (grain/rubble/whitecaps),
`_islet` (sand + scrub + reef ring), `_platform` (oil rig), `_ship` (hull +
wake), `_pier`, `_crack`, `_blob`, `_block`.

Raiden-motif primitives (from stage-screenshot study, see
`_crater`/`_hatch_buried`/…):

- `_crater` — the signature bomb-scar: rough dark bowl, speckled rim with a
  sunlit top-left lip, dim warm glow-cracks inside, ejecta specks. Sprinkled
  on countryside/city/ruins/wasteland/forest/canyon (never ocean).
- `_hatch_buried` — circular metal hatch with bolts, half-creeped by sand
  (canyon; echoes Raiden's embedded stage structures).
- `_canopy` / `_pine` — lumpy broadleaf treetop / 8-spike conifer star,
  both shadowed (forest).
- `_ripple` — dune ripple arcs (canyon).
- `_paddy` / `_track` / `_crate_stack` / `_fence_line` — flooded paddy cell
  (levee frame, water glints, rice rows), winding dirt track with wheel
  ruts and encroaching grass, supply-crate stacks, short post-and-wire
  fences (farmland).
- `_apron` / `_hangar` / `_jet_static` / `_fuel_tank` / `_control_tower` /
  `_radar_dish` — jointed concrete taxiway slab with oil/tire wear, quonset
  hangar with ribbed roof, parked top-down fighter, banded fuel-store tank,
  hex ATC pad with glass cab, radar scope with feed arm (airbase).
- Canyon also has a y-periodic **cliff seam** (dark crack line + sunlit lip
  + rubble scatter) that wraps seamlessly by construction.

Per theme: countryside = forest/farms/river+bridges/pond/road/craters;
city = dense blocks w/ rooftop units + lit windows, sawtooth factory +
smokestacks, road network + crosswalks, parking lot, elevated rail, craters;
ocean = wave streaks/foam/sandbars, islets+reefs, pier, cargo ship, oil
platforms (harbour → open ocean, like Raiden stage 3);
ruins = jagged towers + debris trails, wall fragments w/ floor slabs,
guardrail road stub, scorch beds, craters;
wasteland = strata mesas, dry riverbed, warm cracks, rock clusters, oil
derricks, craters;
forest = canopy clusters + conifer stars (shadowed), mossy glades, creek
with stones, dirt trail, fallen logs, fog ribbons, crash-scar craters;
canyon = distant mesas, sinuous cliff seam + rubble, strata buttes with
chunky offset shadows (stage-4 slab feel), dry riverbed, dune ripples, dry
cracks, boulder fields, buried hatches, fresh craters;
farmland = flooded paddy mosaic with levees/glints/rice rows, winding dirt
track + wheel ruts + footbridges, shadowed groves, farm ponds, barns +
supply crates, levee fences, quiet craters (Raiden II stage-1 fields);
airbase = jointed concrete aprons with oil/tire wear, taxiway with edge
lights, quonset hangars, alert-parked fighters (2×3 scrape + stragglers),
fuel-tank cluster, ATC tower + radar dish, perimeter fences, craters
(Raiden II military-base sectors). Both were composed from screenshots in
`inspiration/`.

## Colour discipline

Keep every terrain colour dim (near-base brightness; lit windows ≤ ~120
brightness). Ships/bullets/items are bright; terrain must never compete.
When adding a theme, sample colours within ±25 of the base gradient. The
tileset path enforces this per theme via `THEME_MEAN` (opaque-pixel RGB
mean 38–48 at bake time; sand/water/concrete themes sit higher so they
don't crush to mud, and glacier sits at 86 because snow below ~70 stops
reading as snow — measured, and it did not help sprite contrast either, so
sprite-vs-bright-patch is a renderer concern, not a `THEME_MEAN` one).

## Adding a new theme

1. If new ground/prop/splat material is needed, generate the raws into
   `assets/textures/tiles/` (materials, must be seamless) and
   `assets/textures/tiles_raw/` (props/splats, on flat pure magenta), list
   them in `scripts/bake_tiles.py`, and run it — the kit manifest drives
   `TileKit`, so nothing is hardcoded there. Then
   `config/stage_theme.py`: add to `StageTheme`; use it in a
   `LevelSpec.theme` or as a `ThemePhase` in some level's `phases` (a
   phase swap also needs the new
   (theme, seed) art baked before `scripts/build.py` will pass its art
   gate).
2. `terrain/compose.py` (tileset path, the default): add a
   `_near_<theme>` composition to `_NEAR` (dispatch stays with the code it
   routes to) and a far-layer material pair
   `FAR_PAIR` row in `terrain/theme_table.py` (which is also where
   `THEME_MEAN`, the per-theme brightness target, lives — that file is data
   only, so retuning a theme never means reading logic).
   `terrain/procedural.py`: add gradient in `_theme_gradient` (used by
   both paths), optionally a vector `_paint_<theme>` registered in
   `_PAINTERS` as the no-tileset fallback.
3. `python scripts/bake_terrain.py` — regenerate the shipped PNGs (the
   script bakes every (theme, level-seed) pair the schedule references).
4. `tests/test_terrain.py` covers every `StageTheme` member automatically
   (parametrized over `list(C.StageTheme)`); the bake/coverage tests will
   fail until the new theme's art is baked.

## Sector handoff (`terrain/handoff.py`)

Changing sector used to be a load: the ground disappeared, a new map was built
on the render thread, and the frame dropped. `SectorHandoff` makes the change
something the player watches instead: the incoming sector is exposed by an edge
that travels down the play field, so both sectors are on screen (and scrolling)
during the sweep. The boundary is a hard clip plus a thin scanline that fades as
the sweep completes — the sector change is an event, so it is allowed a line the
mid-sector boundary deliberately does not have.

The sweep lasts `HANDOFF_SECONDS` (2.4 s), longer than the SECTOR CLEAR banner,
so the reveal is never over before the banner leaves. Because a handoff is not a
`TerrainTrack`, the renderer's background update and draw both route through it
while it lives, and `update_background` promotes the incoming track when the edge
reaches the bottom. `dt` and the speed scale are respected: pausing freezes the
sweep rather than letting it finish behind the pause menu.

## Losing a ship must not move the ground (`ensure_terrain`)

A track *is* the camera's memory: `TerrainTrack.t` records how far the sector
has scrolled and the zone schedule is read from it. `Game` holds no scroll state
at all, so the only thing that can put the ground backwards is the renderer
building a new track.

That is what dying used to do. `_enter_ready()` ran again after the SHIP DOWN
banner and called `set_terrain()` for the sector the craft was already flying
over, which produced a fresh track at `t = 0`: the tiles visibly changed under a
ship the camera never moved — during the banner, the world is still scrolling at
half speed, so the jump happened against ground the player watched moving.

`Renderer.ensure_terrain(level, seed)` is the honest form of "show this sector",
idempotent in the sense that matters here: when the ground already on screen has
the same `terrain.sector_key` (its zones plus map seed — the same identity the
prefetch worker uses, so nobody can disagree about what "the same ground" is),
the existing track is kept, including a handoff mid-sweep. A different sector
still builds. `App._start_game()` clears the terrain first, because a restart is
a new world — the deliberate opposite of a respawn.

## Prefetch (`prefetch.py`)

One daemon worker thread builds what the *next* minutes of play need, off the
render thread:

- `request_sector(level, seed)` builds that sector's zone maps (the expensive
  part: an 800×480 procedural composition plus its two parallax layers).
- `request_art(*names)` warms sprite sheets through the renderer's own
  `SpriteBank`, so the first frame that needs a boss blits instead of loading.
- `sector_track(level, seed)` hands over a finished `TerrainTrack`, **or None**.

Three properties make this safe to splice into the frame loop:

1. **It is never required.** Every consumer treats `None` as "load it the old
   way". A broken map, a disabled prefetcher, or a thread that never got
   scheduled all degrade to the pre-optimisation behaviour.
2. **A take is a transfer, not a copy.** Maps carry mutable scroll offsets, so
   handing maps to a track removes them from the cache; two live tracks must
   never drag the same parallax. The failed take re-queues the sector.
3. **Failures are swallowed.** An exception in the worker is a missed
   optimisation; the worker keeps going.

The cache is bounded (`MAX_SECTORS`, oldest evicted) and `Bank.sheet()` holds a
lock only while *loading* a sheet, which is why prefetching sheets helps without
putting contention on the draw path.

Checkpoints live in the app, not in the prefetcher: at the half of a sector's
wave the sector's own boss art is queued; at half hull on that boss the next
sector and its boss are queued. `TerrainTrack` schedules zones over
`plan_span(level)` = `level.wave_seconds`, so a longer sector keeps changing
ground instead of sitting on the last zone for half its length.

Measured on this machine (SDL dummy video, so no GPU blit): a steady sector
updates and draws in ~11.6 ms median per frame, mid-sweep with two live sectors
~13.0 ms (+12 %) for the 2.4 s of the transition.

## Renderer integration

- `Renderer.set_terrain(level_spec, seed)` / `clear_terrain()` — the
  renderer builds the `TerrainTrack` from `level.phases` (single zone when
  empty), or adopts a prefetched one when `set_prefetch()` was given a
  prefetcher that has the sector ready.
- `Renderer.handoff_terrain(level_spec, seed)` starts a `SectorHandoff` from the
  current ground into the new sector, and reports whether there was ground to
  hand off from.
- `Renderer.update_background(dt, speed_scale)` routes to terrain when set,
  otherwise to the starfield. Speed scales: PLAYING 1.0, TITLE/transitions
  0.5, PAUSED 0.0 (see `App._update`).
- `draw_field` draws terrain + 1 px field outline instead of
  flat fill + starfield when terrain is active.

## One bake scale: painting the size that is blitted

The ground used to be painted at 2x and filtered down per slice, because the baked
PNG pipeline was authored that way (`SS = 2`: "baked PNGs live at 2x for extra
detail; runtime loads them once and downscales"). The streamed path inherited the
resolution and therefore inherited a filter pass on every slice. Follow one
material's texel through it:

    256 (material PNG)  ->  160 (the bake pitch `TILE`)
                        ->   80 (the per-slice halving)
                        ->  156 (on screen, window at 1.95x)

The supersample ended with **fewer** pixels than the material had before it was
halved, and what it definitely bought was a resample between painting and blitting.

Now: `Plane(..., scale=SS)` means two plan pixels per painted pixel, so the painted
plane arrives the size the game blits, and `TerrainStrip` no longer filters it.
`supersample=True` keeps the old route for comparison. Measured: **0.55 s -> 0.16 s
per slice (3.4x)** for the same 800x278 band. The scroll, the plan and the encounter
positions stay in bake pixels - only the paint resolution changed, so the speed the
player sees is untouched.

Four boundaries had to follow the plane's scale, and three of them had previously
been "fixed" in the opposite direction, so each carries a comment: `_band` (a
feature query is in plan units, so a painted extent is multiplied by the scale - the
earlier bug *divided*), `_upsample` (relief sample positions), `_view`/`_grid` (tile
pitch and phase), and `_raster` (positions and brush radius).

## Masks are the geometry's, not the window's

`_raster` used to clamp a mask's box to the plane. That makes a feature's **shape**
depend on which window happened to paint it, and the pixels that moved were the outer
rows of the kept band - a line at every boundary, magnitude ~10/255. A box may now
reach `_PAD` beyond the window (clamped there, so a wrapped road cannot ask for a
three-canvas surface), and `Mask.clip()` is the only way anything writes.

The slice-vs-one-window comparison - the only test that separates "consistent" from
"complete" - has never read zero before this and now reads **0.000% on every slice,
including the last** (was 0.068% there, 37% at its worst).

Two traps found on the way, both worth not repeating: `x1 - x0 <= _PAD` looks like a
sanity check and silently deletes every disc on the map (a tree crown is 20 px, the
pad is 48); and `TerrainStrip(downscale=False)` used to mean "paint at plan size and
blit it unscaled", which is why the flag is now `supersample` and the draw guard
checks the band's actual height instead of a boolean.

`scripts/study_slice_seams.py` compares two neighbouring windows over their overlap
and now reports the outer `_PAD` rows separately. Exact agreement over the whole
overlap is not the right gate and is not achievable: a world row is only ever *shown*
from the window for which it is interior, and the outer rows are where each window's
feather has just finished being clipped. `test_a_slice_shows_the_same_ground_as_the_truth`
in `tests/test_level_paint.py` is the gate.

## The far layer's lattice only covered half the window

`paint_far` scatters its distant range on a 280 px world lattice, and walked that
lattice over `canvas.h` - which since the resolution change is PAINTED pixels, not
world rows. Result: no distant range at all in the lower half of every strip window.
Measured against a one-window reference, slices 4-7 of eight disagreed on
**21% to 54% of their pixels**, scattered rather than at edges - which is what "some
tiles are fine, others ok, some are just wrong" looks like from the cockpit. Fixed by
multiplying the extent by the plane's scale; those slices now read **0.000%**.

The reason this survived the suite is that the slice-vs-reference test only ever
painted the **near** layer. It is parametrised over both now, and over eight slices
instead of four: with a short reference, the lattice is walked over nearly the whole
window in every slice and the bug hides below the crop.

## Cache by name, never by address

`_pitch_tile` cached scaled material tiles under `id(surface)`. When a second
`TileKit` was built, a fresh surface took a freed address and the cache answered with
the material that used to live there, so which ground appeared depended on what had
been painted earlier in the run. Keyed by `(name, pitch, fade, patch)` now.

## Open: painting a slice is not fully order-independent

The first slice's window is clamped at the world start, and it disagrees with a
one-window reference on ~0.7% of pixels (mean 2, max 6 per 255) in an isolated run and
more in a full-suite run - and in a full run an interior slice has shown 0.3%. Ruled
out by measurement, not by argument:

 - every individual pass (relief, fields, water, roads, greens, buildings, cover) and
   the material underlay agree **bit-for-bit** between a 652-row and a 4640-row window
   over the same world rows;
 - widening the strip margin 96 -> 160 -> 256 changes **no pixels**;
 - painting the same slice before and after the window is recreated at a different
   size differs on **0.000%** of pixels, so cached surfaces surviving a mode change is
   not it either.

So the residue is in the composition and depends on what ran before, in ways not yet
pinned. The test does not pretend otherwise: it bounds total disagreement and gates
the **structure** of a line - a row disagreeing on >25% of its pixels at >=5/255 -
because a line is 1-3 rows of 278, i.e. 0.4-1.1% of a band, small enough to slip under
any threshold loose enough to absorb scattered rounding. That gate was checked against
invented cases: it fails a 2-row line at 9/255 and at 5/255, passes residue at <=3
across half the pixels, and passes a compact 100x100 blob (a blob is not a line, and
the volume bound catches it).
