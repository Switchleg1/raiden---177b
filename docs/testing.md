# Testing

```
python -m pytest tests -q          # full suite (322 tests, ~75 s)
```

Runs pygame-free (model) and with `SDL_VIDEODRIVER=dummy` (view/app/terrain).

## Layout

| File                  | Covers                                                |
|-----------------------|-------------------------------------------------------|
| `test_physics.py`     | sub-stepping, tunnelling guards, clamps, circle hits   |
| `test_items.py`       | weighted drops, RNG reproducibility, bounds, **cosmetic phase is reproducible yet never shared by a cluster — and never drawn from the game RNG**, so a renderer detail cannot shift the simulation stream |
| `test_entities.py`    | per-kind enemy movement (incl. darter dive geometry), boss patterns, bullets |
| `test_new_enemies.py` | the four specialists and the decisions they force: splitter → exactly `split_count` shards fanned left/right and **no chain-splitting**, shards weaker + diverging, bomber shells are fat/slow, burst only after `shell_fuse` and throw a radial fragment fan, rammer slides its lock toward the player then **commits to the frozen column** (a last-second dodge is not followed) and never fires, only the bomber lobs shells, all three introduced with sectors to spare, **shards never appear in a spawn table**, kind → sheet → baked-file wiring |
| `test_game.py`        | spawn director, collisions, item apply, bomb (incl. `BOMB_BOSS_DAMAGE`), mine kills vs shield, full 5-level smoke run |
| `test_app_menu.py`    | **mouse-click menu regressions** (quit-confirm flow must not be double-activated); save data redirected to `tmp_path` via `C.TEST_DATA_DIR` |
| `test_app_window.py`  | **display lifecycle regressions**: `set_mode` never runs after startup; fullscreen via `toggle_fullscreen()` (reverts setting on failure), window scale via `Window.size`, vsync applies next launch, viewport letterbox math in logical space, audio-only changes never touch the window |
| `test_terrain.py`     | baked PNGs shipped+match procedural bake for every scheduled (theme, level-seed) pair, all themes build/draw, determinism, wrap offset bounded, no HUD bleed, procedural fallback, phase schedule weights/boundaries, dissolve changes art then settles, empty phases rejected, renderer builds TerrainTrack |
| `test_audio_music.py` | music build-plan ordering (one track per pool first), incremental per-track publishing, one broken track must not kill the playlist (render stubbed, no mixer) |
| `test_state_machine.py` | **transition table as traffic law**: every state declared, SHUTDOWN reachable from everywhere and terminal, no self-transitions, full winning + losing run walkable, submenus open from title/pause only, **PLAYING→VICTORY** (regression: the final SECTOR CLEAR asked for VICTORY from PLAYING, the table refused it and the win silently never landed), illegal moves raise and leave state untouched |
| `test_scores.py` | leaderboard storage: round-trip, missing file ≠ corruption, corrupt file quarantined then ignored, junk rows dropped, ranking/trim/tie order, `rank_of` on empty + partial + full tables, initials sanitiser |
| `test_high_scores_app.py` | leaderboard through the real App: title/pause entry points, banner → `NAME_ENTRY` for a placing run, typing/arrows/backspace, Enter signs the table (row + highlight), Esc leaves it anonymous, a non-placing run skips entry |
| `test_reinforcements.py` | boss escort waves: silent before the boss, first wave after `ESCORT_FIRST_WAVE`, **launches stop the instant the boss dies** (no farming), on-screen cap per sector, small craft only, seeded positions, cadence ramps to its clamp; power-ups carry across sectors but reset on death/new game |
| `test_boss_music.py` | six boss cues are flagged `drive`, faster than every level cue, denser bed than the same bar without drive, render audible short loops; **boss pool is third in the audio build plan**, keys published per pool, `play_boss_music()` reports false until live and never repeats itself |
| `test_boss_habits.py` | the nine bosses are nine fights: every sector maps to a habit, **no two bosses share a movement strategy or an attack sequence**, the entry is an entrance and not a teleport (side bosses start outside the field), **a boss is silent until it lands**, volleys follow the habit's declared order and downward volleys actually travel down, a wall volley always leaves a 90 px corridor, cluster shells only come from the shell primitive, enrage quickens the rhythm instead of calming it, a fighting boss never leaves its band, and the same seed reproduces the same fight |
| `test_shield_fx.py` | the bubble never hides the craft: baked bubble is wider than the hull, **not one of the hull's own pixels moves when the shield is on** (measured against the renderer's own hull mask; drawing the bubble on top changes them by 30+ levels), the deploy pop happens once per shield and is derived rather than stored, the threat flare lights on the side the shot is coming from and ignores your own gunfire, and rendering the effect spends none of the run's seeded RNG |
| `test_sprites.py`   | sprite-sheet manifest integrity (tile addressing round-trips, every anim tile in-bounds), baked sheets shipped + **match fresh procedural bake** (stale-art detector), painter determinism, white hit-flash silhouette keeps alpha mask, `tinted()` recolours and keeps the alpha mask (+ per-tint cache), explosion playhead lifecycle/cap in `Effects`, **whip model**: attaches, replaces Vulcan, expires, forward reach, arc within `WHIP_LEN`, **pickup art**: every kind owns 4 animating tiles, every pod covers its collision circle (art is never smaller than the hitbox), the shared aura orbits and is hollow at the centre, pod accent / aura tint / vector colour all agree with `ITEM_COLORS`, renderer integration (sprites+fallback, plasma switch at weapon lvl 4, pod art → glyph fallback with no sheets, high-contrast draws vectors without a bank) |

## House rules

- Model tests instantiate `Game`/entities with explicit `random.Random(seed)`
  — any test flakiness means a determinism leak (global `random` usage).
- Any test touching the real App must monkeypatch `C.TEST_DATA_DIR` first
  (never write user save files from tests).
- pygame-display tests post synthetic `pygame.event.Event`s and call
  `app.process_events()` directly — no real window needed.
- `conftest.py` installs an autouse fixture that guarantees a pygame display
  exists (32×32 scratch surface under the dummy driver) before any test blits.
  Without it, `test_terrain.py` passed in the full suite and failed when run
  alone — suites that only pass together hide an import-order dependency.
- Table files are tested as data: `test_sprites.py` walks `sheet_table.SPRITES`
  (tile addressing round-trips, every anim tile in bounds), `test_terrain.py`
  parametrizes over every `StageTheme`, `test_state_machine.py` over every
  `TRANSITIONS` entry. Adding a row without its art/rule is a red test, not a
  runtime surprise.

## Headless smoke of the real app

```
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
    python main.py --self-test 240    # frames, exits 0
```

## Quality gates (all clean as of the dead-code / table-file cleanup)

- `ruff check src tests scripts main.py` → 0 errors
- `mypy --ignore-missing-imports src scripts main.py` → 0 errors (94 source
  files; the extra modules are the persistence package and the table files)
- pytest → 322 passed (boss habits, shield bubble, terrain phases, sprites/whip/pickup pods, specialists included)
- `python scripts/audit_symbols.py` → 0 flags (declarations in `src/` that nothing references; the census counts table keys and strings as uses, exit code 1 when anything is flagged)
- self-test → 240 frames, exit 0

The gate is the four commands above, in that order; `pytest`'s exit code is the
verdict (its summary line does not always survive a pipe on Windows).
