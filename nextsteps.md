# Next steps

State at hand-off. HEAD is the commit "Architecture doc lists the app package's new
modules", and everything up to it is committed with the full suite green.

## Done since the first hand-off (all committed, suite green, maps re-baked)

- Trees were scattered per screen twice (`design/cover.py`): countryside 208 -> 74
  items/screen, wasteland 526 -> 43.
- City cross streets run the full length of the city.
- `paint/road_table.py`: city and airbase streets, and all highways, stopped throwing
  dirt splats onto their verges.
- One main river (and one wash/channel) per sector: `water_table.WATER_RATE`.
- **Bridges**: the deck's angle came from "the first path vertex within 60 px" and
  defaulted to along-the-road; it is now the route's heading at the crossing
  (`paint/roads._heading_at`), its length is the channel it spans (`_wet_span`), and
  its alpha is multiplied by the water mask so it exists over water and nowhere else.
- **Trees and houses**: `_tree_clearance` (crown reach + the building's art reach, asked
  per building), `tree_clear_of_buildings` (shrinks a tree beside a house instead of
  refusing it) and `reconcile_foliage` (run once at the end of planning, because a
  place's trees are planted before the houses exist). Highway pylons step over houses.
- City yards are the city's own ground (`cobble_moss`), not `grass_lush`.
- Volcanic ground rebalanced over crust/obsidian/ash/gravel with a cooler rock ramp.
- New tests: `test_no_crown_lies_over_a_roof`, `test_a_bridged_road_keeps_running_under_
its_deck`.

Whole-sector renders: `scripts/..//tmp` style one-pager - plan with
`Geom(h=strip_length(spec), cyclic=False)`, paint with
`TerrainStrip(plan, "near", slice_h=rows, margin=STRIP_MARGIN).paint(0)`, flip
vertically (band row == plan y). `scripts/dump_sector.py <theme> --seed N --slices 0`
does the same for one theme.

## Still open

- **User playtest** of neighbourhoods, woods, lakes, tree density, bridges.
- **City density is a gameplay decision, so it is the user's.** Measured on a full
  sector: 1 992 building probes, 1 038 placed; of the refusals 720 are parked cars that
  did not fit a lot and 233 are footprints hanging past the end of the strip. Cars are
  660 of the 1 038, so a block that looks empty at zoom-out is mostly a car park, and
  `city_table.BLOCK_MIX` (towers 4 of 13 in the core) plus `TOWER` scale 0.56-0.72 are
  the knobs. Raising them fills the ground the player flies over, which is why it needs
  an opt-in. The 233 refused footprints at the strip's ends are candidates whose
  ART hangs past the boundary: they cost planning time and paint nothing.
  Pushing the outer blocks 140 px inboard was tried and is wrong - it moves the
  blocks off the map, buildings drop from 1 038 to 965 and edge refusals rise
  from 233 to 871. The row walk has to stop asking; the grid must not move.
- Trees may still stand in the channel in one clump per sector (`_shore_clear` asks the
  reach, not the wet mask), and are drawn over roads and each other; only roofs are
  protected.
- Highway interchanges (ramps onto the city grid) are not built; no traffic on the
  highway yet (car/truck props exist, only parked ones are used).
- Long dry sectors still show 2-3 washes side by side where a theme asks for several
  (`WATER_RATE`), and mountain ranges are modest (`mountain_table.RANGES`).

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
