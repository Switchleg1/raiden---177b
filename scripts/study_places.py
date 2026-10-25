"""Why does a place fail to build? Count the reasons.

The plan answers "no" for a reason, and the reason is the fix. This runs the
planner with `_rect_free` wrapped so every rejection is attributed, and reports
what each place actually produced - roads, parcels, masts and buildings per
blueprint - so a blueprint that lays a lane and then loses every house is
visible as what it is.

    python scripts/study_places.py                    # every theme, one seed
    python scripts/study_places.py --theme countryside --seed 7 --screens 6
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((8, 8))

from terrain import siteplan  # noqa: E402
from terrain.siteplan import SPEC, Geom, _ink_rect  # noqa: E402


def main(argv: list[str]) -> int:
    theme = "all"
    seed, screens = 3, 6
    if "--theme" in argv:
        theme = argv[argv.index("--theme") + 1]
    if "--seed" in argv:
        seed = int(argv[argv.index("--seed") + 1])
    if "--screens" in argv:
        screens = int(argv[argv.index("--screens") + 1])

    # Wrap the one gate that refuses a footprint, and say WHY it refused.
    real = siteplan._rect_free
    why: dict[str, int] = {}

    def probe(plan, rect):
        if real(plan, rect):
            return True
        x0, y0, x1, y1 = rect
        g = plan.geom
        key = "off-strip"
        if x0 < 10.0 or x1 > g.w - 10.0:
            key = "off-strip"
        else:
            j0, j1 = siteplan._span(y0, y1, g.rows, g.cell)
            i0, i1 = siteplan._span(x0, x1, g.cols, g.cell)
            tally = {"built": 0, "wet": 0, "steep": 0}
            for j in range(j0, j1 + 1):
                for i in range(i0, i1 + 1):
                    if plan.built[j][i]:
                        tally["built"] += 1
                    if plan.wet[j][i]:
                        tally["wet"] += 1
                    if plan.relief[j][i] > 0.42:
                        tally["steep"] += 1
            if max(tally.values()) > 0:
                key = max(tally, key=tally.get)
            else:
                key = "water"
        why[key] = why.get(key, 0) + 1
        return False

    # `place_building` lives in siteplan and calls `_rect_free` by global name, so
    # patching the module attribute is enough - no alias chasing.
    siteplan._rect_free = probe

    themes = sorted(SPEC) if theme == "all" else [theme]
    bad = 0
    for t in themes:
        t0 = time.perf_counter()
        p = siteplan.plan_site(t, seed, Geom(h=1120 * screens, cyclic=False))
        dt = time.perf_counter() - t0
        # footprints must never overlap - the headline property
        r = [_ink_rect(b.kind, b.x, b.y, b.scale, b.angle) for b in p.buildings]
        ov = sum(1 for i in range(len(r)) for j in range(i + 1, len(r))
                 if min(r[i][2], r[j][2]) > max(r[i][0], r[j][0])
                 and min(r[i][3], r[j][3]) > max(r[i][1], r[j][1]))
        grp: dict[str, int] = {}
        for b in p.buildings:
            grp[b.group] = grp.get(b.group, 0) + 1
        mat: dict[str, int] = {}
        for f in p.fields:
            mat[f.mat] = mat.get(f.mat, 0) + 1
        rk: dict[str, int] = {}
        for rd in p.roads:
            rk[rd.kind] = rk.get(rd.kind, 0) + 1
        wd: dict[str, int] = {}
        for w in p.woods:
            wd[w.kind] = wd.get(w.kind, 0) + 1
        want = dict.fromkeys((), SPEC[t].places) if False else SPEC[t].places
        flag = ""
        if ov:
            flag = "  <== OVERLAPPING FOOTPRINTS"
            bad += 1
        print(f"{t:12s} bld={len(p.buildings):3d} plan={dt:5.2f}s "
              f"places={','.join(want) or '-'}")
        print(f"{'':12s}   by group   {dict(sorted(grp.items()))}")
        print(f"{'':12s}   roads      {dict(sorted(rk.items()))}")
        print(f"{'':12s}   field mats {dict(sorted(mat.items(), key=lambda kv: -kv[1])[:5])}")
        print(f"{'':12s}   woods      {dict(sorted(wd.items()))}"
              f"  fields={len(p.fields)} water={len(p.water)} "
              f"greens={len(p.greens)} overlap={ov}{flag}")
    siteplan._rect_free = real
    print("\nwhy footprints were refused:", dict(sorted(why.items(),
                                                      key=lambda kv: -kv[1])))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
