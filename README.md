# Raiden Shadow

An original vertical shoot-'em-up arcade game in the spirit of classic 1990s
arcade shmups, built with [pygame-ce](https://pyce-community.org/). It reuses
the engine shell of *Breakout Classic* (letterboxed 800×600 renderer, menus,
settings, persistence, procedural synthwave music) with a completely new game
model: a transformable fighter, an upgradable Vulcan cannon, homing-side
missiles, an energy whip, screen-clearing smart bombs, enemy waves with
per-sector bosses that call in escort fighters, a retractable energy shield, and
a falling power-up system. The campaign is nine sectors of 51 to 75 seconds of
wave before the boss appears, each scrolling through two crossfading terrain
themes and changing sector with the ground itself sweeping in — no load hitch;
**each of the nine bosses fights differently** —
its own entry, movement habit and attack repertoire (spirals, walls, sweeping
lances, pinwheels, minefields) — each gets its own synthesized fight theme, and
runs end in a three-letter arcade leaderboard.

## Disclaimer

- **Raiden Shadow is an original homage.** It is **not affiliated with,
  endorsed by, or connected to Seibu Kaihatsu, Taito, or any other rights
  holder.** "Raiden" is a trademark of its respective owners and is referenced
  here only to describe the genre/style the game pays tribute to.
- **No third-party assets are used.** Every sprite sheet and terrain map is
  *baked from code* by scripts that ship in this repo (pygame-ce geometry,
  seeded RNG) — the PNGs in `data/` are build artifacts, not imported art, and
  can be deleted and regenerated deterministically. The seamless ground /
  prop / splat source images the terrain tileset is cut from are
  AI-generated originals kept in `assets/textures/` (source only, never
  shipped); `scripts/bake_tiles.py` seam-wraps, chroma-keys and feathers them
  into `data/textures/tiles/`, and every shipped map re-derives from that kit.
  Enemy and boss art works the same way: generated stills in
  `assets/textures/sprites_raw/` are keyed to `assets/textures/sprites_src/`
  and then animated by code into `data/textures/sprites/` (core pulse, engine
  flare, roll, bob) — no frame is drawn by hand, nothing is fetched at
  runtime, and the keyed stills are bake-time input that never ships.
  Every sound effect and music track is synthesized at runtime from
  pure-Python DSP code. No fonts are used beyond the pygame-ce default.
- All game code and generated content are provided under the MIT license
  (see [`LICENSE`](LICENSE)).

## Running

```sh
# from the repo root, no install required (needs pygame-ce + numpy):
python main.py
```

The game source lives in `src/`; `main.py` puts it on the import path.
Multi-class areas are packages with **one class per file** (`config/`,
`entities/`, `input/`, `sprites/`, `state/`, `terrain/`, `ui/`, `app/`),
each `__init__.py` re-exporting the old flat-module surface, so
`import config as C` etc. never changed; single-purpose modules
(`game.py`, `audio.py`, …) stay flat. `pip install -e .` is only a
shortcut for installing the runtime dependencies — the game itself is
never installed.

`run.bat` in this folder is a personal launcher for the development agent; it
is not part of the game.

### Controls

| Action | Keyboard & mouse | Gamepad-style alt |
| ------ | ---------------- | ----------------- |
| Move   | WASD / Arrow keys | or move the mouse (craft tracks the cursor) |
| Fire   | hold `SPACE` or left mouse button | |
| Bomb   | `X` or right mouse button | |
| Pause  | `P` / `ESC` | |

Menus are mouse-driven (`ESC` backs out). When a run lands on the leaderboard,
the initials screen takes over the keyboard:

| Action | Initials entry |
| ------ | -------------- |
| Type a letter / digit | `A`–`Z`, `0`–`9` (fills the slot, steps right) |
| Pick from the wheel | `↑` / `↓` (or `W` / `S`) |
| Move between slots | `←` / `→` (or `A` / `D`) |
| Clear a slot | `BACKSPACE` |
| Sign it | `ENTER` — `ESC` skips, the run stays anonymous |

Menus are fully mouse-navigable; settings (display mode, vsync, FPS cap,
volume split, music theme, hit-effect toggle, power-up system toggle) live in
the Options screen and persist between runs.

### Self-test (headless)

```sh
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python main.py --self-test 240
```

### Unit tests

The game model (physics, entities, items, game rules) is free of pygame
imports and is covered by pytest:

```sh
python -m pytest tests -q
```

### Baked art (terrain & sprites)

All artwork is painted by code and baked to PNG once — gameplay only loads
files (~15 ms/map), and what it needs next is loaded on a worker thread ahead of
the frame that asks for it (`prefetch.py`). Sector terrain ships in
`data/textures/terrain/`; each sector scrolls through two *terrain phases* (e.g.
Sector 1 dissolves from countryside into farmland mid-level, Raiden-style)
scheduled over that sector's own wave length, and the sector change itself is a
2.4 s reveal drawn from two live sectors (`terrain/handoff.py`) rather than a
swap. So all 18 theme/level pairs the nine sectors schedule are baked. Sprite sheets (the raw-keyed hero
craft, ten enemy kinds, nine per-sector bosses, bullets, whip beads, 3-tier
explosions, nine pickup pods and one shared orbiting pickup marker) ship in
`data/textures/sprites/`, and the seamless material /
prop / splat tilekit in `data/textures/tiles/`. The keyed stills the sheets
are animated from stay in `assets/textures/sprites_src/` — bake input, never
shipped (see docs/architecture.md, "data/ vs assets/").

After changing any painting code, regenerate (each step is deterministic):

```sh
python scripts/bake_tiles.py        # ~2 s: assets/textures -> data/textures/tiles
python scripts/bake_terrain.py      # ~25 s for all 18 scheduled maps
python scripts/bake_sprite_raws.py  # ~2 s: generated stills -> keyed sources
python scripts/bake_sprites.py      # ~2 s for all 31 sheets (raws -> animation)
python scripts/build.py             # PyInstaller onedir -> dist/RaidenShadow/
```

Tests assert the shipped PNGs match a fresh procedural bake, so stale art
fails the suite — and `scripts/build.py` refuses to package when any baked
file the schedule references is missing.

To *look* at the art without launching the game:

```sh
python scripts/preview_sprites.py                    # frame contact sheets
python scripts/preview_entities.py                   # boss + roster per sector
python scripts/preview_fx.py --only shots --scale 2  # bullets over real terrain
python scripts/preview_fx.py --only items            # pickups over real terrain
```

`preview_fx.py` is the honest one: it composites the shot/whip/explosion sheets
over a scrolled sector at 1:1, which is the only way to tell whether a bolt
reads against bright glacier ice or a dark factory floor.

### Building a Windows app folder

```sh
build.bat                # Windows: art check, package, zip, sha256, self-test
build.bat full           # ... after running ruff, mypy and pytest first
build.bat gate           # tests only, no packaging
python scripts/build.py  # the same packaging step, any platform
```

`build.bat` is the one command for a shippable folder: it bakes anything
missing, installs PyInstaller if needed, runs `scripts/build.py`, then boots
the *built* exe headless (`--self-test 240` with dummy video and audio) so the
artifact is proven rather than assumed. Options: `rebake`, `nozip`, `noverify`,
`console`, `pause`. It never waits for a keypress unless asked with `pause`, so
CI and scripted callers cannot hang on it.

Packaging is PyInstaller `--onedir`; the script copies `data/textures/` into
the app folder with `shutil.copytree` (the game resolves its art relative to
the executable), zips the folder, and writes a `.sha256` sidecar so a download
can be verified before running. It refuses to package when a baked texture
directory is empty.

## How it works

- `game.py` — the complete simulation model (fixed 120 Hz timestep, seeded
  RNG, event-list API). No pygame. Deterministic and unit-tested.
- `entities/` / `items.py` / `physics.py` — craft, enemies, bullets, falling
  power-ups, sub-stepped collision-safe motion. Each sector's boss carries its
  own sprite sheet (`LevelSpec.boss`), so a mid-fight boss switch is data.
- `app/` — state machine (title → ready → playing → life/level transitions →
  results → initials entry → high-score table), audio & particle reactions to
  model events.
- `sprites/` — sprite-sheet system: manifest of 30 tiled sheets (player craft
  with left/right banking frames, 10 enemy kinds, 9 sector bosses, 4 bullet
  types, whip bead FX, 3 explosion tiers, 9 pickup pods sharing one tinted
  orbiting marker) with per-sheet animation sequences, a
  lazy loading `Bank` (white hit-flash silhouettes via `BLEND_RGB_MAX`,
  per-colour recoloured copies via `BLEND_RGB_MULT`),
  `rawkit.py` which turns one keyed still into an animated sheet (core pulse,
  engine plume, roll, bob — and the hero's ten banking poses from one still)
  with painters as fallback, `fxkit.py`, a premultiplied-float tile compositor
  used for every bolt, bead, fireball and pickup pod (pygame draws overwrite
  alpha instead
  of compositing it, so layered glow is impossible with them), and
  `painters.py`, which bakes the shipped PNGs. See
  [docs/sprites.md](docs/sprites.md).
- `ui/` — renderer for the letterboxed 800×600 canvas: title attract scene
  (parallax starfield with the hero craft cruising/banking and a parade of the
  real enemy sprites descending) and sector terrain maps (in-game), baked
  sprite sheets for ships/bullets/explosions with hand-vector fallbacks, HUD
  with weapon/missile/bomb gauges, menus.
- `terrain/` — vertically wrapping two-layer parallax terrain: thirteen
  themes (countryside, farmland, swamp, city, ruins, glacier, volcanic,
  ocean, airbase, industrial, wasteland, canyon, forest).
  `TerrainTrack` schedules each sector's *phase zones* over the sector's wave
  length and dissolves between them as the sector scrolls (weights live on
  `LevelSpec.phases`); `SectorHandoff` reveals the *next* sector with a
  downward sweep while both sectors keep scrolling, and `ensure_terrain` keeps
  that ground in place when the craft is re-served after a death (the camera
  never moved, so the tiles must not). Maps are
  painted from the tileable kit — Raiden motifs include glowing bomb-scar
  craters, buried metal hatches, strata buttes with chunky offset shadows,
  canopy and conifers — and BAKED offline (`scripts/bake_terrain.py`) into
  `data/textures/terrain/*.png`; gameplay just loads those (~15 ms/map).
  Numpy ground-texture / grain passes and per-object shadow sheets give the
  painted, non-flat look; `build_procedural()` remains as a fallback.
- `audio_effects.py` / `audio.py` — the sound-effect vocabulary (every effect
  name + how close two repeats may be) as a table, and the DSP engine that
  synthesizes it at runtime.
- `music_content.py` / `music.py` / `drum_kit.py` / `instruments.py` — the score
  as data (33 level cues, 20 attract cues, 6 boss cues, each with its scale, drum
  kit, groove, melody family, bass line and voicing) and the threaded synth that
  renders three looping pools: attract themes, level themes and boss fight cues
  (faster, denser, with a tritone alarm bed). Drums are a small procedural
  rompler — a kit is a set of voice parameters rendered once per sample rate,
  then hits are added in — with tempo-selected grooves (swing, ghost notes,
  bar-8 fills) so no two sectors keep the same time. Melody families (`hero`,
  `lyric`, the stock `base`) and relative bass lines (octave pops, chromatic
  approach tones) give each cue its own narrative role, and a cue may hand a
  melody to a synthesised flute, violin, string section, pluck or bell instead of
  a raw wave — a flute states a phrase and a violin takes up the answer. Each
  sector draws a cue from **its own pool** of 3-5 (`LEVEL_CUES`), never the one
  that just played. No audio files; the pool renders incrementally in the
  background, in an order that gives every sector its own cue within half a
  minute, so a boss appearing in the first minute still gets music.
- `prefetch.py` — the worker thread that composes the next sector's terrain and
  warms the next boss's sprite sheets, so a sector change never pays for either
  on the render thread. It is an optimisation with a correctness-free failure
  mode: any consumer that finds nothing ready just loads it the old way.
- `persistence/` — per-user settings, run statistics and the **top-10
  leaderboard** (`scores.json`) in the OS app-data folder (isolated from
  Breakout Classic).

## Documentation

- [docs/architecture.md](docs/architecture.md) — layering, module map, game
  event API, determinism rules, known pitfalls.
- [docs/terrain.md](docs/terrain.md) — terrain map system and how to add themes.
- [docs/sprites.md](docs/sprites.md) — sprite sheets, the generated-raw
  pipeline and anchors, animation, explosions, the whip, and the bake workflow.
- [docs/music.md](docs/music.md) — the rendered soundtrack: voice engine,
  procedural drum rompler, synthesised instruments, grooves and kits, per-sector
  cue pools, cue keys, melodic-material policy.
- [docs/testing.md](docs/testing.md) — test layout, quality gates, headless
  smoke commands.

## The roster

Six core hostile types hold the line — grunt (straight descent), weaver,
darter (fast diagonal dive), gunner (hovers, aims at you), sentry (near-static
radial turret) and heavy (slow, tanky) — and three specialists each force one
specific decision:

- **Bomber** — a wide, slow seeder that lobs fat cluster shells. They are
  dodgeable as shells and much less dodgeable as the radial fragment fan they
  burst into after their fuse, so shooting it *early* is the answer.
- **Splitter** — weaves down at you and breaks into two fast, weak shards when
  killed; the shards cannot split again, so one death is exactly two extras.
- **Rammer** — no gun. It paints your column for half a second, then commits to
  that frozen column at increasing speed: move early and it misses you
  completely, panic late and the charge lands.

Each sector's spawn table introduces the specialists gradually (splitter from
sector 2, rammer from 3, bomber from 4) and weights them upward through
sector 9; shards are corpse content only and never spawn directly.

## Power-up system

Enemies drop weighted falling icons: Vulcan power-ups (wider gun spread up to
level 5, bolts turn into plasma orbs from level 4), missile upgrades, extra
smart bombs,
an energy shield you can see (a bubble that deploys around the craft and flares
when a shot is closing in), medals, bonus lives — and the **energy whip**: for
~12 s
your cannon is replaced by a crackling energy lash that you sweep through
enemies by moving (aimed by the cursor/keys, whipping in an arc in front of
the craft). Hazards too: jammers that downgrade your Vulcan and floating
mines that cost a life unless you are shielded. The whole system can be turned
off in Options (same toggle style as Breakout Classic). Weapon power is kept
when you clear a sector and start the next one, and resets when your craft is
destroyed — carry a maxed cannon into a boss, not through a grave.

Each pickup falls as a bevelled **pod**: dark casing, an accent-bright rim, a
recessed window carrying its symbol, four rivets and a specular sweep that
travels across the frames. Hazards are octagons, because "do not touch" has to
be a shape and not only a colour. Around every pod a marker **orbits** — three
comet blades and counter-rotating gauge ticks, punched hollow in the middle so
the pod stays the thing you aim at. One neutral marker is baked and recoloured
per kind at runtime, so nine distinct colours cost one sheet; the pod colour,
the marker colour and the high-contrast icon colour all come from one palette.
The marker deliberately over-frames the hitbox: the pod is what you have to
touch, the orbit is what you notice falling.

`python scripts/preview_fx.py --only items` shows all nine over a scrolled
sector, at 1:1, through the same drawing code the game uses.

## Boss fights and the leaderboard

Every sector ends with its own boss. While one is on screen:

- **Escorts answer the call.** The boss sends out small craft on a timer that
  speeds up with the sector (2.4 s after the boss lands, then every 3.4 s down
  to 1.5 s), 1–3 at a time, capped at 4–8 alive. The second the boss dies the
  call stops — you can't farm a dying core.
- **The music changes.** Six synthesized boss cues (156–176 BPM, four-on-the-
  floor, 16th-note hats, tritone alarm stab) replace the level track the frame
  the boss appears, and a different one is picked per fight — as is the level
  track itself, drawn from that sector's own pool instead of one cue repeated
  across the run. The boss pool is rendered early in the background so a
  first-minute boss still gets music.
- **The run is signed.** A score that makes the top 10 goes to the initials
  screen, then to the attract-mode table (rank, initials, score, sector,
  cleared or downed) with your new entry highlighted. High Scores is on the
  title menu and in the pause menu; a run that doesn't place just gets the
  results menu.

## Development

```sh
python -m ruff check src scripts tests   # lint gate (formatting is not enforced)
python -m mypy src                       # type gate
python -m pytest -q                      # unit tests
```

- **One class per file.** A package directory is a layout convention only; its
  `__init__.py` re-exports the old flat-module surface, so gameplay code never
  changed when modules were split (see [docs/architecture.md](docs/architecture.md)).
- **Determinism.** The model uses its own seeded RNG (`zlib.crc32`-derived),
  never `random` or wall-clock time. Terrain art is seeded per (theme, index)
  pair, so a given tile is identical everywhere it appears.
- **Headless first.** Every check above must pass with dummy SDL drivers;
  screenshots land in `screenshots/`, never in the repo root.

## Project layout

```
main.py                  launcher (prepends src/ to sys.path, --self-test)
src/                     one class per file; tables live in table files
  config/    screen · sim · player · weapons · enemy_* · item_* · levels ·
             palette · settings · boss_habit · boss_behaviours · …
  terrain/   terrain_map.py · procedural.py · tilekit.py · compose.py ·
             theme_table.py · layer.py · track.py
  sprites/   sheet_table.py · manifest.py · rawkit.py · fxkit.py ·
             painters.py · bank.py · anim.py
  entities/  enemy.py · player.py · bullet.py · whip.py · bosskit.py
  ui/        renderer.py · constants.py · effects.py · explosion.py · menu.py …
  state/     game_state.py · transitions.py · machine.py · errors.py
  input/     controller.py · viewport.py · ship_axis.py · actions.py
  persistence/ paths.py · json_store.py · stats*.py · score_entry.py ·
               scores_table.py · scores_store.py · settings_store.py
  app/       app.py (state machine) · settings_rows.py
  game.py · items.py · physics.py · audio.py · audio_effects.py ·
  music.py · music_content.py · drum_kit.py · instruments.py
data/      RUNTIME DATA — the only art a running game or build reads
  textures/  tiles/ · terrain/ · sprites/
assets/    SOURCE / BAKE-TIME MATERIAL — never shipped, safe to delete
  textures/  sprites_raw/ (generations) · sprites_src/ (keyed stills) ·
             tiles_raw/ · tiles/ (kit prep scratch)
scripts/
  bake_tiles.py · bake_terrain.py · bake_sprite_raws.py · bake_sprites.py
  preview_sprites.py · preview_entities.py · preview_fx.py · preview_bosses.py
  build.py · entry.py · audit_symbols.py
tests/           365 pytest tests (model, sprites, terrain, music, state, app)
docs/            architecture.md · terrain.md · sprites.md · music.md · testing.md
```

## Notes on the original

The game is a homage to the vertical-shmup era of the early 1990s, not a
recreation of any specific product: no data, art, sound, level layout or
script from any commercial game is present, read, or reverse-engineered. The
reference screenshots kept under `inspiration/` were used only to
discuss *style* (camera, palette, silhouette readability) during development
and are not shipped or loaded by the game.

## License

MIT — see [`LICENSE`](LICENSE).
