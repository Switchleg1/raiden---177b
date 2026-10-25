# Next steps

State at hand-off. HEAD is the commit "Architecture doc lists the app package's new
modules", and everything up to it is committed with the full suite green.

## Done since the first hand-off (all committed, suite green, maps re-baked)

- Trees were scattered per screen twice (`design/cover.py`). Countryside went from 208
  to 74 items per screen, wasteland from 526 to 43.
- City cross streets run the full length of the sector.
- `paint/road_table.py`: city and airbase streets, and all highways, no longer throw
  dirt splats onto their verges.
- One main river per sector on river themes (`water_table.WATER_RATE`). Before, every
  real sector had two parallel full-length rivers.

Whole-sector overviews: `screenshots/terrain/_overview_c.png` (countryside 1, city 3,
wasteland 9). Regenerate with a script like the one in the session: plan with
`Geom(h=strip_length(spec), cyclic=False)`, paint with
`TerrainStrip(plan, "near", slice_h=rows).paint(0)`, then flip vertically.

## Still open

- Wasteland, canyon and airbase sectors of 30+ screens get 2–3 washes that run side
  by side for their whole length. Consider one long wash plus short side washes, like
  the river tributaries.
- City: many grass/yard blocks (`city_table.BLOCK_MIX`). Fewer would read as denser
  downtown.
- Highway interchanges (ramps onto the city grid) are not built.
- Mountain ranges are modest. Possible next steps: amplitude (`mountain_table.RANGES`)
  and pines on the flanks of alpine ranges.
- A playtest by the user of neighbourhoods, woods, lakes and tree density is still
  pending.

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
