# Next steps

State at hand-off. HEAD is the commit "Architecture doc lists the app package's new
modules", and everything up to it is committed with the full suite green.

## Uncommitted in the working tree (verify, then commit)

Two fixes found while viewing whole-length sectors. **The suite has not been run on
them yet.**

1. `src/terrain/design/cover.py` (`_cover`): the tree-scatter count was scaled by strip
   length **twice**. `plan_site` already multiplies `spec.woods` by `g.screens`, and
   `_cover` did `randint(lo, hi) * g.screens` again. Measured before the fix: a
   40-screen wasteland had 464 trees/screen and sector 1 (countryside) had about 150
   from scatter alone (208/screen total). The fix removes the second multiply.
   One-screen (baked) maps multiply by 1, so their plans should be unchanged.
2. `src/terrain/design/circulation.py` (`_city_grid`): cross streets now span the whole
   strip (`range(200, h - 100, 460)`). They used to cover only 12%–90% of the sector,
   which left a screen-tall empty block at each end of the city.

To verify:
```
.venv/Scripts/python.exe -m pytest -q --maxfail=0
.venv/Scripts/python.exe /tmp/trees.py        # (recreate: counts Wood items per screen by kind)
```
Then look at a whole sector again (`scripts/dump_sector.py <theme> --seed N --slices 0`,
or render with `LevelSpec.scars` as in the session). Target: roughly 60–90 tree
items per screen in countryside, and much less carpeting in the wasteland. If the
countryside is still forest-heavy, also thin out the woodland places
(`terrain/design/places/vocabulary_table.py`: woodland `per`, and the 120–240 trees
each in `woodland.py`).

## Still open from the visual review

- **Orange dirt splats scattered across the city and along every road.** Source:
  `terrain/paint/roads.py`, the shoulder "soiling" splats (`splat_dirt`, 30% every
  3rd vertex). Drop them for paved themes (city, industrial, airbase) or for
  `main`/`highway` roads, or make them a per-theme table entry.
- City: a lot of grass blocks, and two parallel rivers plus a highway. Consider one
  river per city (`water_table.WATER_RATE` keyed by theme) and fewer park/yard blocks
  in `city_table.BLOCK_MIX`.
- Wasteland/volcanic read monotone (dead-tree carpet, near-black ground). After fix 1,
  revisit their `tree_props`/`woods` in `design/spec_table.py`.
- Mountain ranges are visible but modest. Possible next steps: stronger crest
  amplitude (`mountain_table.RANGES`) and pines on the lower flanks of alpine ranges.
- Highway interchanges (ramps onto the city grid) were planned but not built.
- Traffic on highways (the car/truck props exist; only parked cars are used).

## Tooling notes

- I can view images: write a PNG and read it. Use a **new filename** each time
  (the viewer caches by path), and wait a second after writing.
- The image generator (`pi-imagegen`) is broken: it hardcodes the dispatcher model
  `gpt-5.5` (`~/.pi/agent/npm/node_modules/pi-imagegen/imagegen.ts:23`), which the
  ChatGPT account no longer serves. New props are drawn procedurally by
  `scripts/paint_props.py` and shipped with `scripts/bake_tiles.py`. A new prop needs
  its INK entry in `terrain/design/art_table.py` (measured; a test checks it), and
  `ART_FRONT` if its front isn't drawn at the bottom.
- The command layer turns `\\n` into real newlines inside heredocs. Write Python patch
  scripts with the Write tool instead.
- Piping `ruff check` into `tail` hides its exit status. Don't chain commits on it.
- After any terrain painter/planner change: `scripts/bake_terrain.py`, then the full
  suite (`test_baked_matches_procedural` compares baked maps).

## Layout after the cleanup (for orientation)

- `src/` holds packages only: app, audio, config, entities, game, input, level, music,
  persistence, sprites, state, terrain, ui.
- Terrain: `terrain/plan/` (data, one class per file), `terrain/design/` (planner;
  places in `design/places/`), `terrain/paint/` (painter). These three re-export
  nothing (import cycles), so import from the defining module.
- Lookups live in `*_table.py` beside their code. Dispatch tables name methods by
  string (app `control_table`/`signal_table`, `entities/flight_table`,
  `input/keymap_table`).
- Push to GitHub is still pending (the user pushes manually); many commits are local
  only.
