# Raiden Shadow — Architecture

Original Raiden-style vertical shooter. Reuses the GUI, settings/persistence,
synth audio engine and fixed-timestep discipline of the sibling
*Breakout Classic* project. All art is derived from code (terrain tileset and
sprite stills are generated sources kept in `assets/`; shipped scripts key,
crop and animate them into `data/`, and vector painters remain the runtime
fallback); all sound is synthesized at runtime.

## Layering (strict, one-way imports)

```
                 ┌──────────┐
                 │   app/   │  state machine, wiring, event consumer
                 └─┬───┬──┬─┘        input, audio, effects, transitions
                   │   │  └─────────► ui/, input/, audio.py  (view/controller;
                   │   │              terrain/, sprites/ — pygame allowed)
                   │   └────────────► game.py (model API)
                   ▼
      game.py · entities/ · items.py · physics.py · state/ · config/
      (pygame-FREE, deterministic, unit-tested)
```

- **Model layer never imports pygame.** `Game.update()` returns a
  `list[dict]` of events; the app owns sound/particles/state reactions.
- `config/` is the single source of constants (bounds, weapons, enemies,
  items, levels, palettes, Settings schema).
- `terrain/` is view-layer only: it paints backgrounds, never affects
  gameplay and is never imported by the model.
- `sprites/` is view-layer only: art sheets + animation playheads. The
  whip *model* lives in `entities/whip.py` (points only); the renderer
  decides how to paint them.
- **One class per file.** Multi-class modules are packages whose
  `__init__.py` re-exports the public surface, so `import config as C`,
  `from state import State`, `import sprites` etc. keep working
  unchanged; single-purpose modules (`game.py`, `audio.py`, `music.py`,
  `items.py`, `physics.py`) stay flat.
- **Tables live in table files.** Anything a human would retune —
  level/enemy/item/boss tuning, sprite-sheet records, music content,
  theme ground data, the state-transition map — sits in a module that
  holds data only, named for what it lists (`sheet_table.py`,
  `music_content.py`, `theme_table.py`, `transitions.py`,
  `audio_effects.py`). Code reads those tables; it does not embed them.
  The exception is dispatch tables that name *functions*
  (`compose._NEAR`, `bosskit._ATTACKS`, `painters._BAKE`) — those are
  code-shaped and stay with the code they route to.
- **`data/` is what ships, `assets/` is what art was made from.** The
  running game loads only `data/textures/{sprites,terrain,tiles}`.
  Keyed source stills (`assets/textures/sprites_src/`), raw generations
  and tile prep material stay in `assets/` and are never copied into a
  build; a checkout with `assets/` deleted still runs and still bakes.

## Modules

Every package below keeps one class (or one topic) per file; its
`__init__.py` re-exports the old flat-module surface.

| Module (package) | Responsibility                                                 |
|--------------|--------------------------------------------------------------------|
| `config/`   | All tuning constants — one topic per file (`screen`, `sim`, `player`, `weapons`, `enemy_stats`, `item_rules`, `levels`, `palette`, `settings`, …) plus `EnemySpec/ItemKind/LevelSpec/StageTheme`, `Settings` (schema shared with Breakout for file compat). |
| `physics.py`  | `advance()` bounded sub-stepping (anti-tunnelling), circle hits, clamps. |
| `config/boss_behaviours.py` | **Each sector boss's habit**: `BOSS_HABITS` maps the boss's sprite sheet (exactly what `LevelSpec.boss` routes onto `Enemy.sheet`) to a `BossHabit` — a named temperament, a movement strategy, an ordered attack repertoire, an entry vector, and the enrage threshold. Nine habits, no two sharing a move or a sequence; `habit_for()` answers for every boss and falls back for a tenth that does not exist yet. Data only: `moves`/`attacks` are strategy *names* resolved by `entities/bosskit.py`, so adding a boss means adding a table row, never an `if` chain. |
| `entities/bosskit.py` | Executes those habits: `move()` handles the scripted entrance (descend from above, or sail in from off the side) then one of nine path strategies (strafe, pendulum, orbit, hunt, lunge, eight, hop, edge, stalker), and `attack()` fires one primitive per call — aimed, fan, ring, spiral, pinwheel, wall, mine, shell, spray, beam. A boss is **silent until it lands**, and an enraged boss fires faster and adds a bullet to every volley. |
| `entities/` | `player.py`, `enemy.py` (per-kind movement+patterns), `bullet.py`, `whip.py` (energy-lash point chain). Enemy `update(dt, player_x, player_y, fire_cb, bullet_speed, rng)`; `fire_cb(x, y, vx, vy, shell=0, fuse=0.0)` — a non-zero `shell` is a cluster shell. Specialist kinds: **bomber** lobs fusing shells, **splitter** weaves down (`split_into`/`split_count` on its spec), **rammer** tracks `lock_x` for `RAMMER_LOCK_TIME` then charges the frozen column and never fires, **shard** is the diverging corpse child. |
| `items.py`    | Falling `Item`, weighted `roll_item`, seeded RNG.                   |
| `game.py`     | `Game`: spawn director, **boss escort waves** (`_update_escorts`, armed by `_spawn_boss`, capped by `C.escort_cap`), firing, whip timer/contact damage, collisions, item apply/drops, bombs, lives, level flow; routes each level's boss art (`LevelSpec.boss` → `Enemy.sheet`); `_burst_shells()` detonates bomber shells when their fuse expires and `_split_enemy()` spawns splitter children (children cannot chain). Emits event dicts (`SIG_BOSS` on spawn). |
| `state/`    | `game_state.py` state enum (BOOT/TITLE/READY/PLAYING/LIFE_LOST/LEVEL_COMPLETE/GAME_OVER/VICTORY/PAUSED/SETTINGS/HOW_TO_PLAY/**NAME_ENTRY**/**HIGH_SCORES**/SHUTDOWN), `transitions.py` the legal-movement table, `machine.py` the enforcer. PLAYING→VICTORY is legal: the last boss ends the run where it died. |
| `input/`    | `viewport.py` letterbox math, `ship_axis.py` smoothed axes, `controller.py` `InputController` (keys+mouse → axes, fire-hold, edge-action set), `actions.py` action ids. |
| `audio_effects.py` | The SFX vocabulary as data: every effect name, `EFFECT_NAMES`, and `MIN_GAP` (how close two repeats of the same effect may be). |
| `audio.py`    | Procedural SFX + WAV bytes (reused Breakout synth engine): renders the names from `audio_effects`, gates them by `MIN_GAP`, and owns the music playlists/channels. |
| `music_content.py` | The music as data: the 31 level cues, 19 menu cues and 6 boss cues (`THEMES`/`MENU_THEMES`/`BOSS_THEMES`), the scale table and the bar layouts. A theme is a root note, a bpm, a lead wave and an eight-bar progression. |
| `music.py`    | Threaded procedural synthwave playlist builder that renders `music_content` into looping 16-bit PCM (boss cues set `drive=True`: +50 bpm, four-on-the-floor, 16th hats, tritone alarm).    |
| `terrain/`  | Per-sector scrolling terrain maps: `terrain_map.py` loads baked PNGs; `procedural.py` vector painters; `tilekit.py` loads `data/textures/tiles/` (seamless materials, props, splats + manifest, prepared by `scripts/bake_tiles.py`); `compose.py` seeded, y-periodic tileset compositions; `theme_table.py` per-theme ground data (backdrop material pair + target mean luminance); `track.py` phase schedule (see terrain.md). |
| `sprites/`  | `sheet_table.py` the `SPRITES` records (a sheet may name a `raw` source; several sheets may share one raw), `manifest.py` the path/grid helpers over that table (`sheet_path`, `cols_for`, `tile_count`, `raw_stem`), `rawkit.py` keyed-source → animated cell painter (anchors: glow/plume/spin/flap/bob, incl. auto-detected power cores for bosses) plus `build_player_sheet()` for the hero's 10-pose bank, **`fxkit.py` premultiplied-float tile compositor** (`disc`/`capsule`/`box`/`cone`/`tri`/`annulus`/`bloom`/`window`) used for every bullet, bead and explosion because pygame draws do not composite alpha, `painters.py` procedural painters + bake, `bank.py` lazy loader, `anim.py` playheads + hit-flash silhouettes (see sprites.md). |
| `ui/`       | `renderer.py` canvas painting (terrain/starfield, sprite blits w/ vector fallback, HUD, menus), `effects.py`/`particle.py`/`explosion.py`, `button.py`/`menu.py` widgets, `fonts.py` cache. |
| `app/`      | `app.py` owns pygame lifecycle, fixed 120 Hz substeps, transitions, event→fx/audio mapping, menus, run stats; `settings_rows.py` settings-menu row table. |
| `persistence/` | Settings, lifetime statistics and the **leaderboard**, one module per kind: `paths.py` (where files live), `json_store.py` (atomic write + quarantine), `stats.py`/`stats_store.py`, `score_entry.py` + `scores_table.py` (rank rules) + `scores_store.py`, `settings_store.py`. Public surface is re-exported, so callers still say `persistence.load_scores`. Files live under `C.APP_AUTHOR/C.APP_SLUG`; corrupt files are quarantined, never trusted; renamed fields keep reading their old key (`stats_store.LEGACY_KEYS`); `C.TEST_DATA_DIR` seam redirects in tests. |

### Source tree

```
src/
  app/         app.py · settings_rows.py
  config/      app_info · screen · sim · player · weapons · enemy_kind ·
               enemy_spec · enemy_stats · item_kind · item_rules ·
               stage_theme · theme_phase · level_spec · levels · palette ·
               settings        (each a plain .py; __init__ re-exports all)
  entities/    bullet.py · player.py · enemy.py · whip.py · bosskit.py
  input/       actions.py · viewport.py · ship_axis.py · controller.py
  persistence/ paths.py · json_store.py · stats.py · stats_store.py ·
               score_entry.py · scores_table.py · scores_store.py ·
               settings_store.py
  sprites/     sheet_table.py · manifest.py · rawkit.py · fxkit.py ·
               anim.py · bank.py · painters.py
  state/       game_state.py · transitions.py · errors.py · machine.py
  terrain/     common.py · layer.py · procedural.py · tilekit.py ·
               theme_table.py · compose.py · terrain_map.py · track.py
  ui/          fonts.py · constants.py · button.py · menu.py · particle.py ·
               explosion.py · effects.py · renderer.py
  audio.py · audio_effects.py · game.py · items.py · music.py ·
  music_content.py · physics.py
```

Table modules (`config/*`, `sheet_table.py`, `music_content.py`,
`theme_table.py`, `transitions.py`, `audio_effects.py`) hold literals and
nothing else, so retuning never means reading logic.

Every package `__init__.py` re-exports its members, so absolute imports
(`import config as C`, `import terrain`, `from state import State`,
`import sprites`, `import persistence`) resolve to the package and see the
same public names as before the split.

## Game event API (`Game.update(dt, move_x, move_y, firing, bomb)`)

`Game.update` returns events; the app reacts in `_on_signal`:

| event type      | payload                     | app reaction                              |
|-----------------|-----------------------------|-------------------------------------------|
| `shoot`         | —                           | SFX SHOOT (gapped)                         |
| `missile`       | —                           | SFX MISSILE                                |
| `enemy_killed`  | `x,y,color,kind`            | particles + sprite explosion (tier via `EXPLOSION_TIER`) + SFX EXPLOSION |
| `boss_spawn`    | `name`                      | BOSS_WARN, screen flash                    |
| `boss_down`     | `x,y,color`                 | big explosion + shake                      |
| `item_drop`     | `kind,x,y`                  | (visual only; item exists in model)        |
| `medal`         | `amount`                    | score popup handled inside model           |
| `powerup`       | `kind`                      | POWERUP SFX + HUD flash                    |
| `hazard`        | `kind`                      | HAZARD SFX (jammer / protected mine)       |
| `bomb`          | —                           | BOMB SFX + screen flash + wipe             |
| `life_lost`     | —                           | LIFE_LOST SFX, transition → READY          |
| `level_clear`   | —                           | LEVEL_COMPLETE SFX, transition             |
| `game_over`     | —                           | GAME_OVER SFX, results                     |
| `victory`       | —                           | VICTORY SFX, results                       |

Signals `life_lost/level_clear/game_over` return True from `_on_signal` and
break the substep loop; the app then starts the appropriate transition.

## Key rules (learned the hard way)

1. **Determinism**: every random draw in model code must come from the
   injected `random.Random` (`Game.rng` → `Enemy.update(..., rng)`,
   `Enemy.spawn(..., rng)`). No global `random.*` in gameplay paths.
2. **READY must not drive `Game.update`** — the craft is pre-served by the
   app; running the sim during READY would spawn/fire enemies off-screen.
   Auto-launch after `READY_TIME`.
3. **Mouse clicks are handled by exactly one layer.** Menu buttons consume
   MOUSEBUTTONDOWN in `App._handle_menu_events`; `InputController` must not
   turn mouse clicks into `ACT_CONFIRM` (it caused "Quit to Desktop does
   nothing": dialog opened then instantly answered by the duplicate event).
4. **Powerups respect the single `Settings.powerups` toggle** — beneficial
   drops *and* hazards (JAMMER, MINE) all gate behind it, mirroring Breakout.
5. **Bomb vs boss uses `BOMB_BOSS_DAMAGE`** (60), not the normal BOMB_DAMAGE.
6. `Game` owns level progression (`level_index`, `start_level`,
   `advance_level`, `is_final_level`); app calls `_enter_ready()` after
   transitions and `set_terrain(level.theme, level_index+1)` there.
7. **Music tracks are published one-by-one, first menu + first level track
   first.** The audio worker used to render the whole menu playlist (~13 s)
   before any level track (~45 s total), so starting the game right after
   launch found an empty level pool and stayed silent until returning to
   the menu (`_music_build_plan` fixes the order; `App._update` retries
   `play_level_music()` every frame while `_music_want == LEVEL_KEY`).
   A per-track render failure must skip, not abort the playlist.
8. **The boss pool renders third**, right after the first menu + level cue, so
   a fight starting inside the first minute has music (otherwise the whole
   level playlist had to finish first). `SIG_BOSS` → `play_boss_music()`;
   `_resume()` re-picks via `Game.boss_alive()`, and `App._update` retries
   while the pool is still being rendered. Music is *not* cut when the boss
   dies — the level cue resumes at the next sector boundary.
9. **A boss's band is a fighting rule, not an entrance rule.** `BOSS_TOP` /
   `BOSS_BOTTOM` keep a *fighting* boss in its lane, but the arrival is a
   spectacle: it drops from above (`y = FIELD_TOP - 80`) or glides in from
   outside a side wall. Clamping during the glide (both the generic wall clamp
   in `Enemy.update` and `bosskit.keep_in_band`) teleported bosses onto the
   band on their first frame and pinned side entries at the field edge, so both
   return early while `boss_step < 0.0`.
10. **The shield bubble is presentation.** It is derived from the one number the
    model already publishes (`7.0 - Player.shield`), so it needs no state, draws
    no RNG and consumes no bullet; the deploy pop replays when a shield stacks on
    a running one. Its art is deliberately wider than the hull and blitted
    *before* it (`tests/test_shield_fx.py` fails if the craft's own pixels move).
    The threat flare reads the nearest hostile bullet for the same reason — the
    renderer is allowed to look, never to spend.
11. **Score pipeline**: `SIG_GAME_OVER`/`SIG_VICTORY` → `_commit_run()` writes
   the run stats and ranks the score (`P.rank_of`). A placing score goes to
   `NAME_ENTRY` (3 initials, typed or arrow-selected) → `save_scores` →
   `HIGH_SCORES` with the new row highlighted; a non-placing score keeps the
   classic results menu. Power-ups carry across sectors (`start_level(...,
   keep_power=True)`); they reset on `new_game()` and on a re-serve.
- **`pygame.display.set_mode()` runs exactly once, at startup.** Recreating
   the display at runtime wedges the present path (measured on Windows/
   pygame-ce 2.5.7: after ANY mid-game `set_mode` — even same-size, same
   flags — the window keeps pumping events and the game keeps running but
   the screen never updates again; verified with GDI screen sampling).
   The display is therefore created **once with `pygame.SCALED`**: the
   display surface stays logical 800×600 forever and SDL scales it to
   whatever the window is. Runtime changes are attribute updates on the
   *existing* window: window scale → `pygame.window.Window.size` (wrapper
   via `Window.from_display_module()`), fullscreen → `display.
   toggle_fullscreen()`, and `_recompute_viewport()` pre-letterboxes inside
   the logical surface so SDL's non-uniform stretch cancels out (e.g.
   1920×1080 → viewport (100,0,600,600); mouse events arrive in logical
   coords automatically under SCALED). After any mode change
   `_sync_display_surface()` re-adopts `pygame.display.get_surface()` —
   a stale `self.window` is the same frozen-screen symptom.
   **VSync cannot be changed live** (pygame-ce keeps no GL context current
   for `SDL_GL_SetSwapInterval`, and the only alternative is `set_mode`);
   the setting persists and applies at next launch. Failed toggles revert
   the setting instead of recreating anything (`tests/test_app_window.py`).

## Fixed timestep

`App._update(dt)` runs whole `C.SIM_DT` (1/120 s) substeps; mouse-follow craft
motion is applied per-frame directly to `game.player.x/y` (capped at
`MOUSE_TRACK_SPEED`), keyboard axes are passed through `game.update`.
`ACT_BOMB` is a one-shot flag consumed by the first substep.

## Save data

`C.APP_SLUG = "raiden_shadow"` keeps save data separate from Breakout.
Settings schema is reused verbatim (no new fields → old validator compat).
Tests must set `C.TEST_DATA_DIR` (see `tests/test_app_menu.py`) so they never
touch the user's real save location.

Writes are atomic (`json_store.atomic_write_json`), and a file that fails
validation is renamed `<name>.corrupt.<stamp>` and starts fresh instead of
crashing the game. Renamed fields keep reading their old key
(`stats_store.LEGACY_KEYS`), so a save written before a rename is not reset.

`Stats` is career data collected per install. Only `high_score` is surfaced
today (the HUD's HI readout); `games_played`, `highest_sector`,
`most_enemies_destroyed` and `longest_session` are accumulated and persisted
for a stats screen that does not exist yet — deliberately kept, so that screen
has history to show.

## `data/` vs `assets/`

| Directory | Contents | Shipped |
|---|---|---|
| `data/textures/terrain/` | baked scrolling maps, one per scheduled (theme, level-seed) | yes |
| `data/textures/sprites/` | baked animated sheets (31) | yes |
| `data/textures/tiles/` | seamless materials / props / splats + `manifest.json` (the no-tileset-map fallback reads it) | yes |
| `assets/textures/sprites_src/` | keyed, defringed stills the sheets are animated from | **no** |
| `assets/textures/sprites_raw/` | generations (input to `bake_sprite_raws.py`) | **no** |
| `assets/textures/tiles_raw/`, `assets/textures/tiles/` | tile-kit source art and prep scratch | **no** |

The rule: the running game only ever opens files under `data/`, and
`scripts/build.py` copies exactly `terrain/`, `sprites/`, `tiles/`. Bake-time
input lives under `assets/`, so a stripped checkout — or the shipped build —
carries no art sources and still runs (a sheet with no keyed source falls back
to its vector painter). `RAIDEN_TEXTURE_DIR` relocates the runtime root;
`RAIDEN_SPRITE_SRC_DIR` relocates the keyed bake input.
