# Terrain maps (`terrain/`)

Procedurally painted, vertically scrolling backdrop per sector — homage to
Raiden's stage progression. The campaign runs **nine sectors over thirteen
themes** (countryside, farmland, swamp, city, ruins, glacier, volcanic,
ocean, airbase, industrial, wasteland, canyon, forest); every sector
dissolves through **two terrain phases** (e.g. Sector 1: countryside →
farmland, Sector 4: glacier → ocean), matching Raiden's mid-level
environment changes. View layer only: terrain never affects gameplay and
the model never imports it — adding a theme costs paint code and baked art,
never spawn/enemy logic.

## Phase schedule (`TerrainTrack`)

- `LevelSpec.phases` is a tuple of `ThemePhase(theme, weight)`; weights
  normalise into a `PHASE_PLAN = 46 s` virtual-scroll timeline (level
  lengths vary; the last zone covers the boss approach).
- `TerrainTrack(phases, seed)` builds one `Terrain` per zone (same seed) and
  advances a virtual clock `t += dt * speed_scale` — pausing freezes the
  schedule; the track is recreated in `_enter_ready()`, so sectors always
  replay identically.
- At each zone boundary the new map **dissolves in over the old one** for
  `PHASE_FADE = 1.8 s`: old zone drawn plain, new zone drawn into a
  full-logical-size `SRCALPHA` scratch surface and blitted with a rising
  global alpha. The scratch's HUD band stays transparent, so the HUD is
  never touched.
- All zones scroll every frame (offset arithmetic only — negligible cost),
  so a zone is always at a natural scroll position when it fades in.
- Sector schedules: 1 countryside→farmland, 2 city→ruins, 3 ocean→airbase,
  4 ruins→canyon, 5 wasteland→canyon.
- Every (theme, seed) pair any sector schedules must have baked art; the
  bake script iterates the schedule (`level_art()`) and `build.py` refuses
  to package missing pairs.

## Structure

- **One `TerrainTrack` per sector**, built in
  `Renderer.set_terrain(level_spec, seed)` (called by the app in
  `_enter_ready()`; title screen clears it and falls back to the starfield).
  A `Terrain` is one baked map: three parts:
- Three parts:
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

## Renderer integration

- `Renderer.set_terrain(level_spec, seed)` / `clear_terrain()` — the
  renderer builds the `TerrainTrack` from `level.phases` (single zone when
  empty).
- `Renderer.update_background(dt, speed_scale)` routes to terrain when set,
  otherwise to the starfield. Speed scales: PLAYING 1.0, TITLE/transitions
  0.5, PAUSED 0.0 (see `App._update`).
- `draw_field` draws terrain + 1 px field outline instead of
  flat fill + starfield when terrain is active.
