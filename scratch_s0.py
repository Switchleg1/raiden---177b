import os, sys
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
for k in ("src", "tests"): sys.path.insert(0, os.path.abspath(k))
import numpy as np, pygame
pygame.init(); pygame.display.set_mode((60, 40))
from level.design import _plan_here
from level.strip import STRIP_MARGIN, STRIP_SLICE, TerrainStrip

rows = STRIP_SLICE * 8
plan = _plan_here("countryside", 3, rows)
tv = np.asarray(pygame.surfarray.array3d(TerrainStrip(plan, "near", slice_h=rows, margin=STRIP_MARGIN).paint(0))).astype(int)
kept = np.asarray(pygame.surfarray.array3d(TerrainStrip(plan, "near").paint(0))).astype(int)
d = np.abs(tv[:, :278] - kept).max(axis=2)
bad = d > 0
rows_hit = np.nonzero(bad.any(axis=0))[0]
cols_hit = np.nonzero(bad.any(axis=1))[0]
print(f"diff rows: {rows_hit.min()}..{rows_hit.max()}  ({len(rows_hit)} of 278)")
print(f"diff cols: {cols_hit.min()}..{cols_hit.max()}  ({len(cols_hit)} of 800)")
# connected-ish blobs: cluster the rows
gaps = np.nonzero(np.diff(rows_hit) > 3)[0]
start, segs = 0, []
for gi in list(gaps) + [len(rows_hit) - 1]:
    segs.append((int(rows_hit[start]), int(rows_hit[gi])))
    start = gi + 1
print(f"row clusters (world rows within the band): {segs[:8]} ... {len(segs)} clusters")
