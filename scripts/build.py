#!/usr/bin/env python3
"""Reproducible packaging for Raiden Shadow using PyInstaller.

Produces a portable Windows one-directory build, a ZIP archive, and a SHA-256
checksum. All output goes under ``dist/`` and is safe to delete; nothing user-
specific (settings/statistics/caches) is packaged.

Usage::

    python scripts/build.py            # build, zip, and checksum
    python scripts/build.py --no-zip   # build only
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
APP_NAME = "RaidenShadow"
EXE_NAME = "RaidenShadow"


def _clean(paths: list[Path]) -> None:
    for p in paths:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)


def _check_shipped_art() -> None:
    """Fail packaging when shipped content references unbaked art."""
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    import config as C
    import sprites as SP
    import terrain as T
    missing = []
    for seed, theme in _level_art(C):
        if not all(p.is_file() for p in T.baked_paths(theme, seed)):
            missing.append(f"terrain {seed}:{C.StageTheme(theme).name}")
    for name in SP.SPRITES:
        if not SP.sheet_path(name).is_file():
            missing.append(f"sprite {name}")
    if missing:
        sys.exit("missing baked art: " + ", ".join(missing)
                 + " — run scripts/bake_terrain.py and scripts/bake_sprites.py"
                 " before packaging")


def _level_art(C) -> list[tuple[int, Any]]:
    out, seen = [], set()
    for i, level in enumerate(C.LEVELS):
        seed = i + 1
        for theme in [p.theme for p in level.phases] or [level.theme]:
            if (seed, theme) not in seen:
                seen.add((seed, theme))
                out.append((seed, theme))
    return out


def build(dist: Path, work: Path, noconsole: bool) -> Path:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller is required: pip install pyinstaller")

    _clean([dist / APP_NAME, work / APP_NAME])
    args = [
        "--name", APP_NAME,
        "--noconfirm",
        "--clean",
        "--onedir",
        "--paths", str(SRC),
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(work),
        str(ROOT / "scripts" / "entry.py"),  # package entry point
    ]
    if noconsole:
        args.append("--windowed")   # no console window on Windows
    print("PyInstaller args:", " ".join(args))
    from PyInstaller.__main__ import run as pi_run
    pi_run(args)
    build_dir = dist / APP_NAME
    # Ship baked art next to the bundle so the modules' parents[2]
    # data/textures lookups find it (same layout as the repo).
    _check_shipped_art()
    dest = build_dir / "data" / "textures"
    for kind in ("terrain", "sprites", "tiles"):
        tex = ROOT / "data" / "textures" / kind
        if not tex.is_dir() or not any(tex.rglob("*.png")):
            sys.exit(f"data/textures/{kind} is empty — run the bake scripts "
                     "before packaging")
        shutil.copytree(tex, dest / kind, dirs_exist_ok=True)
    return build_dir


def make_zip(build_dir: Path, dist: Path) -> tuple[Path, str]:
    zip_path = dist / f"{APP_NAME}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for base, _dirs, files in os.walk(build_dir):
            for fn in files:
                fp = Path(base) / fn
                arc = fp.relative_to(build_dir.parent)
                zf.write(fp, arc)
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    # LF, not the platform default: "sha256sum -c" reads the filename off the
    # line, so a CRLF sidecar fails on any non-Windows verifier.
    (dist / f"{APP_NAME}.zip.sha256").write_text(
        f"{digest}  {APP_NAME}.zip\n", encoding="utf-8", newline="\n")
    return zip_path, digest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default=str(ROOT / "dist"))
    ap.add_argument("--work", default=str(ROOT / "build"))
    ap.add_argument("--no-zip", action="store_true")
    ap.add_argument("--console", action="store_true",
                    help="keep a console window for diagnostics")
    a = ap.parse_args(argv)

    dist, work = Path(a.dist), Path(a.work)
    dist.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    build_dir = build(dist, work, noconsole=not a.console)
    exe = build_dir / f"{EXE_NAME}.exe"
    print(f"built executable: {exe} (exists={exe.exists()})")

    if not a.no_zip:
        zip_path, digest = make_zip(build_dir, dist)
        print(f"zip: {zip_path}")
        print(f"sha256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
