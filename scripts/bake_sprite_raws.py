#!/usr/bin/env python3
"""Sprite raw prep: AI generations -> keyed, defringed, trimmed source art.

Reads generation scratch from assets/textures/sprites_raw/<stem>.png and
writes keyed bake input to assets/textures/sprites_src/<stem>.png plus
manifest_src.json (px, coverage, rim luminance, sha1 per entry).

Accepted raw backgrounds (auto-detected per file):
  * a real alpha channel (what the image pipeline usually returns), or
  * flat pure magenta rgb(255,0,255) for hand-keyed generations.

Both paths end in the same normalised form: straight (non-premultiplied)
alpha, the dark feathered rim recoloured to the surrounding hull, a tight
bbox with an even transparent margin, longest side SRC_PX.

src/sprites/rawkit.py animates those into the shipped sheets in
data/textures/sprites/, which is what the game loads.  sprites_src/ is the ONLY
art input the sprite bake needs, and it stays under assets/ because nothing at
runtime ever reads it: a stripped checkout (or a shipped build) has no sprites_src
at all, and the sheets still bake and load.  Re-run this after adding or
replacing a generation, then `python scripts/bake_sprites.py`.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "assets" / "textures" / "sprites_raw"
OUT = ROOT / "assets" / "textures" / "sprites_src"

SRC_PX = 384            # canonical longest side of the keyed source
MARGIN = 0.05           # transparent band kept around the silhouette
MAGENTA_TOL = 90        # chroma distance treated as background
HALO = (24, 250)        # alpha band considered a fringe/feather pixel
# Generations arrive with wide faint bloom (and, in batched sheets, stray
# low-alpha specks) painted around the hull.  Measuring the silhouette from
# any visible pixel lets those specks set the scale, and the craft arrives at
# half size.  Measure the bbox from solid alpha, then fade everything below
# it away instead of cutting it, so no hard rectangle edge is left behind.
SOLID_FLOOR = 190
WISP_FADE = (45, 200)
# The subject is located on a probe grid where one probe pixel is about one
# image pixel; a coarser grid blurs the subject's neighbourhood together and
# starts keeping debris.
CONNECT_PROBE = 512


def load(path: Path) -> np.ndarray:
    im = Image.open(path)
    return np.asarray(im.convert("RGBA"), dtype=np.int16)




def split(path: Path) -> list[tuple[str, np.ndarray]]:
    """One raw file -> [(stem, pixels), ...].

    `e_grunt.png` is a single sprite.  `e_a+e_b+e_c@3x1.png` is a generation
    sheet: rows x cols of evenly divided cells, stems listed in reading
    order.  Batching a generation keeps the art direction consistent across
    a family of enemies and costs one call instead of three.  A batched cell
    is inset before anything else looks at it: whatever crosses a divider
    belongs to two subjects at once, and generated bloom spills past the rule
    it is drawn around.  Names starting with an underscore are scratch and are
    skipped.
    """
    name = path.stem
    if name.startswith("_"):
        return []
    if "@" not in name:
        return [(name, load(path))]
    stems, grid = name.split("@", 1)
    rows_s, _, cols_s = grid.partition("x")
    rows, cols = int(rows_s), int(cols_s or 1)
    parts = [s for s in stems.split("+") if s]
    if len(parts) != rows * cols:
        raise ValueError(f"{path.name}: {len(parts)} stems for a {grid} grid")
    img = load(path)
    h, w = img.shape[:2]
    inset = max(4, int(0.03 * min(h / rows, w / cols)))
    out: list[tuple[str, np.ndarray]] = []
    for i, stem in enumerate(parts):
        r, c = divmod(i, cols)
        cell = img[r * h // rows + inset:(r + 1) * h // rows - inset,
                   c * w // cols + inset:(c + 1) * w // cols - inset]
        if float((cell[..., 3] > 12).mean()) < 0.002:
            raise ValueError(f"{path.name}: cell {stem} is empty")
        out.append((stem, cell))
    return out


def key_background(rgba: np.ndarray) -> tuple[np.ndarray, str]:
    """Return (rgba, mode) where mode is 'alpha' or 'chroma'."""
    a = rgba[..., 3]
    if float((a < 250).mean()) > 0.02:        # genuine transparent border
        return rgba, "alpha"
    r, g, b = (rgba[..., i].astype(np.float32) for i in range(3))
    dist = np.sqrt((r - 255.0) ** 2 + g ** 2 + (b - 255.0) ** 2)
    alpha = np.clip((dist - MAGENTA_TOL) / MAGENTA_TOL, 0.0, 1.0) * 255.0
    out = rgba.copy()
    out[..., 3] = alpha
    # magenta spill on the edge: pull R/B down toward G
    spill = np.clip(np.minimum(out[..., 0], out[..., 2]) - out[..., 1], 0, None)
    out[..., 0] = out[..., 0] - spill * 0.8
    out[..., 2] = out[..., 2] - spill * 0.8
    return out, "chroma"


def defringe(rgba: np.ndarray) -> np.ndarray:
    """Recolour the semi-transparent rim from the solid hull outward.

    Generated PNGs feather their silhouette against a black matte, so rim
    pixels carry near-black RGB.  Scaled down, that rim reads as a dark halo
    under the sprite -- ugly on snow and tarmac.  Flood the hull colour into
    the fringe instead and leave alpha untouched.
    """
    a = rgba[..., 3]
    lo, hi = HALO
    fringe = (a > lo) & (a < hi)
    if not fringe.any():
        return rgba.copy()
    rgb = rgba[..., :3].astype(np.float32)
    src = rgb.copy()
    valid = a >= hi
    for _ in range(48):
        todo = fringe & ~valid
        if not todo.any():
            break
        acc = np.zeros_like(rgb)
        cnt = np.zeros(rgb.shape[:2], dtype=np.float32)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            rv = np.roll(np.roll(valid, dy, 0), dx, 1)
            acc += np.roll(np.roll(src, dy, 0), dx, 1) * rv[..., None]
            cnt += rv
        got = todo & (cnt > 0)
        if not got.any():
            break
        rgb[got] = acc[got] / cnt[got][..., None]
        src = np.where(valid[..., None], src, rgb)
        valid |= got
    out = rgba.copy()
    painted = fringe & valid
    out[..., :3] = np.where(painted[..., None],
                            np.clip(rgb, 0, 255).astype(np.int16),
                            rgba[..., :3])
    return out


def resize_rgba(rgba: np.ndarray, nw: int, nh: int) -> np.ndarray:
    """Resize straight-alpha art without dragging black into the edges.

    Resizing RGBA channels independently averages edge colour toward the
    black of fully transparent pixels, which is exactly the halo defringe()
    exists to remove.  Premultiply, resize colour and alpha separately, then
    divide back out.
    """
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    prem = np.dstack([rgba[..., :3] * a, rgba[..., 3:4]])
    img = Image.fromarray(np.clip(prem, 0, 255).astype(np.uint8), "RGBA")
    small = img.resize((nw, nh), Image.Resampling.LANCZOS)
    got = np.asarray(small, dtype=np.float32)
    na = got[..., 3:4] / 255.0
    rgb = np.where(na > 0.001, got[..., :3] / np.maximum(na, 0.001), 0.0)
    return np.dstack([rgb, got[..., 3:4]]).astype(np.int16)


def _labels(mask: np.ndarray, iters: int = 240) -> np.ndarray:
    """Connected-component labels of mask (4-neighbour propagation).

    Max-propagation on a downsampled grid: cheap, no scipy dependency, and
    it terminates early once labels settle.
    """
    labels = np.where(mask, np.arange(mask.size).reshape(mask.shape) + 1, 0)
    for _ in range(iters):
        nxt = labels.copy()
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nxt = np.maximum(nxt, np.roll(np.roll(labels, dy, 0), dx, 1))
        nxt = np.where(mask, nxt, 0)
        if np.array_equal(nxt, labels):
            break
        labels = nxt
    return labels


def _largest_blob(mask: np.ndarray, drop_border: bool = False) -> np.ndarray:
    """Biggest connected region; optionally discard anything sheet chrome."""
    labels = _labels(mask)
    if not labels.any():
        return mask
    if drop_border:
        edge = np.concatenate(
            [labels[0], labels[-1], labels[:, 0], labels[:, -1]])
        chrome = [int(v) for v in np.unique(edge) if v]
        labels = np.where(np.isin(labels, chrome), 0, labels)
    vals, counts = np.unique(labels[labels > 0], return_counts=True)
    if len(vals) == 0:
        return mask
    return labels == vals[int(np.argmax(counts))]


def _grow_within(seed: np.ndarray, region: np.ndarray) -> np.ndarray:
    """The part of `region` reachable from `seed` (thin struts survive)."""
    labels = np.where(region, np.where(seed, 1, 0), 0)
    for _ in range(240):
        nxt = labels.copy()
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nxt = np.maximum(nxt, np.roll(np.roll(labels, dy, 0), dx, 1))
        nxt = np.where(region, nxt, 0)
        if np.array_equal(nxt, labels):
            break
        labels = nxt
    return labels > 0


def kill_rules(rgba: np.ndarray) -> None:
    """Erase sheet divider rules in place (in a batched generation, a rule is
    a pale bar drawn straight across the cell).

    Rules matter because their glow bridges the craft to the cell border and
    to its neighbours, which wrecks subject detection.  "Solid and spans the
    cell" is not enough to identify one -- a wide siege hull does both -- so
    the test also demands the pale, desaturated grey of printer chrome.
    """
    a = rgba[..., 3]
    solid = a > 200
    mx = rgba[..., :3].max(axis=2)
    mn = rgba[..., :3].min(axis=2)
    pale = (mx - mn < 46) & (mn > 130)
    band = max(2, int(0.012 * max(a.shape)))
    for idx in np.nonzero((solid & pale).mean(axis=1) > 0.72)[0]:
        a[max(0, idx - band):idx + band + 1] = 0
    for idx in np.nonzero((solid & pale).mean(axis=0) > 0.72)[0]:
        a[:, max(0, idx - band):idx + band + 1] = 0


def _keep_mask(alpha: np.ndarray) -> np.ndarray:
    """0..1 weight keeping the subject of a cell and releasing the debris.

    The subject is whatever solid matter is connected to the biggest solid
    blob, grown back out into the glow that hugs it.  A plain alpha bbox cannot
    do this job: batched generations draw pale divider rules across a cell and
    bleed bloom over them, and a bbox treats that chrome as art -- the craft
    then scales down to half size to make room for a line drawn between rows.

    Connectivity has to be judged on solid matter.  At a low threshold the
    bloom of one cell bridges into the next and a neighbour's engine tops come
    along for the ride; at a high threshold only real hull conducts.
    """
    h, w = alpha.shape
    # A coarse probe is cheaper but blind: at 160px one cell pixel is six, so
    # the dilation and feather below reach 40px and swallow the neighbour's
    # engine tops.  At this resolution a probe pixel is about one image pixel.
    s = min(1.0, CONNECT_PROBE / max(h, w))
    small = np.asarray(Image.fromarray(alpha.astype(np.uint8)).resize(
        (max(2, round(w * s)), max(2, round(h * s)))), dtype=np.uint8) \
        if s < 1.0 else alpha
    core = _largest_blob(small > 150)
    if core.sum() < 6:
        core = _largest_blob(small > 90)
    # Grow through *anything* attached (alpha > 16): these illustrations hang
    # their wings and intakes off semi-transparent struts, and a stricter
    # region threshold amputates them.
    blob = _grow_within(core, small > 16)
    for _ in range(2):        # back out into the glow that hugs the hull
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            blob |= np.roll(np.roll(blob, dy, 0), dx, 1)
    if blob.sum() < 0.4 * float((small > 150).sum()):
        return np.ones(alpha.shape, dtype=np.float32)   # off; keep everything
    mask = np.asarray(Image.fromarray((blob * 255).astype(np.uint8)).resize(
        (w, h), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
    # Feather the boundary so a rejection never leaves a hard stair-stepped
    # cut through what used to be soft bloom.  Keep the feather narrow: every
    # pixel it widens is debris that comes back.
    mask = np.asarray(Image.fromarray((mask * 255).astype(np.uint8))
                      .filter(ImageFilter.GaussianBlur(
                          max(1, round(0.004 * max(h, w))))),
                      dtype=np.float32) / 255.0
    return np.clip(mask * 1.4, 0.0, 1.0)


def trim_pad(rgba: np.ndarray, src_px: int) -> np.ndarray:
    kill_rules(rgba)
    rgba[..., 3] = (rgba[..., 3] * _keep_mask(rgba[..., 3])).astype(np.int16)
    a = rgba[..., 3]
    ys, xs = np.nonzero(a > 12)
    if len(xs) == 0:
        raise ValueError("no subject left after debris removal")
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    pad = max(2, int(0.03 * max(y1 - y0, x1 - x0)))
    crop = rgba[max(0, y0 - pad):min(a.shape[0], y1 + pad),
                max(0, x0 - pad):min(a.shape[1], x1 + pad)].copy()
    lo, hi = WISP_FADE
    ca = crop[..., 3].astype(np.float32)
    t = np.clip((ca - lo) / max(hi - lo, 1.0), 0.0, 1.0)
    crop[..., 3] = (ca * t * t * (3.0 - 2.0 * t)).astype(np.int16)
    if float((crop[..., 3] >= SOLID_FLOOR).mean()) < 1e-4:
        raise ValueError("silhouette faded away entirely")
    s = (src_px * (1.0 - 2 * MARGIN)) / max(crop.shape[1], crop.shape[0])
    nw, nh = max(1, round(crop.shape[1] * s)), max(1, round(crop.shape[0] * s))
    small = resize_rgba(crop, nw, nh)
    out = np.zeros((src_px, src_px, 4), dtype=np.int16)
    x0, y0 = (src_px - nw) // 2, (src_px - nh) // 2
    out[y0:y0 + nh, x0:x0 + nw] = small
    return out


def save(rgba: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.fromarray(rgba.astype(np.uint8), "RGBA").save(
        buf, "PNG", compress_level=9)
    path.write_bytes(buf.getvalue())


def rim_lum(rgba: np.ndarray) -> float:
    """Mean luminance of the rim band (higher = no dark halo left)."""
    a = rgba[..., 3]
    band = (a > HALO[0]) & (a < 250)
    if not band.any():
        return 0.0
    lum = rgba[..., :3].astype(np.float32) @ np.array([0.3, 0.6, 0.1])
    return float(lum[band].mean())


def main() -> int:
    if not RAW.is_dir():
        raise SystemExit(f"no raw dir: {RAW}")
    info: dict[str, dict] = {}
    todo: list[tuple[str, np.ndarray]] = []
    for path in sorted(RAW.glob("*.png")):
        try:
            todo.extend(split(path))
        except Exception as exc:                     # noqa: BLE001
            print(f"SKIP     {path.name:<28} {exc}")
    for stem, rgba in todo:
        rgba, mode = key_background(rgba)
        raw_rim = rim_lum(rgba)
        # defringe AFTER scaling: the scale itself creates the soft rim.
        rgba = defringe(trim_pad(rgba, SRC_PX))
        out = OUT / f"{stem}.png"
        save(rgba, out)
        cov = float((rgba[..., 3] > 128).mean())
        info[stem] = {
            "kind": "sprite_src", "px": SRC_PX, "mode": mode,
            "coverage": round(cov, 3),
            "rim_lum": round(rim_lum(rgba), 1),
            "rim_lum_raw": round(raw_rim, 1),
            "bytes": out.stat().st_size,
            "sha1": hashlib.sha1(out.read_bytes()).hexdigest()[:12],
        }
        print(f"prepared {stem:<20} {mode:<6} cov {cov:.2f} "
              f"rim {raw_rim:5.1f} -> {info[stem]['rim_lum']:5.1f} "
              f"{info[stem]['bytes'] // 1024}K")
    (OUT / "manifest_src.json").write_text(
        json.dumps({"px": SRC_PX, "sprites": info}, indent=1))
    total = sum(v["bytes"] for v in info.values())
    print(f"manifest: {len(info)} sources, {total // 1024} KiB total -> "
          f"{OUT / 'manifest_src.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
