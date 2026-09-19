#!/usr/bin/env python3
"""Symbol census: declarations in `src/` that nothing ever references.

Run from anywhere::

    python scripts/audit_symbols.py          # flags + tally, exit 1 if flagged
    python scripts/audit_symbols.py -q       # tally line only

Method, deliberately dumb and greppable: parse every ``.py`` file for
declarations (module level plus one level into classes), then count
word-boundary occurrences of each name across the repo's Python text. A name
that occurs exactly once is only ever written down, never read - an orphan.

References inside tables count as uses, which is what we want: an entry that
only a dict key or a manifest string mentions is still a live entry. This is
also why the census excludes its own file - a tool that names symbols in prose
would mark them used.

Two categories:

``ORPHAN``          one occurrence anywhere (the declaration itself).
``UNUSED-IN-SRC``   never referenced by ``src/``; kept only if no test or
                    script references it either, in which case it is reported
                    here and a human decides whether it is public API.
"""
from __future__ import annotations

import argparse
import ast
import collections
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP_PARTS = ('build', 'dist', '__pycache__', '.git', 'screenshots', '.venv')
SELF = pathlib.Path(__file__).resolve()


def _py_files() -> list[pathlib.Path]:
    out = []
    for p in sorted(ROOT.rglob('*.py')):
        rp = p.resolve()
        if rp == SELF:                        # never score against our own prose
            continue
        if any(part in SKIP_PARTS for part in rp.parts):
            continue
        out.append(rp)
    return out


FILES = _py_files()
TEXTS = {p: p.read_text(encoding='utf-8', errors='replace') for p in FILES}


def _zone(path: pathlib.Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    for name in ('src', 'tests', 'scripts'):
        if rel.startswith(name + '/'):
            return name
    return 'root'


def _declarations(path: pathlib.Path) -> list[tuple[str, str, int]]:
    """(dotted name, kind, line) for a file's public-ish declarations."""
    tree = ast.parse(TEXTS[path], filename=str(path))
    found: list[tuple[str, str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = 'class' if isinstance(node, ast.ClassDef) else 'def'
            found.append((node.name, kind, node.lineno))
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and _is_table_name(tgt.id):
                    found.append((tgt.id, 'const', node.lineno))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _is_table_name(node.target.id):
                found.append((node.target.id, 'const', node.lineno))
        if isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.append((f'{node.name}.{sub.name}', 'method',
                                  sub.lineno))
    return found


def _is_table_name(name: str) -> bool:
    """UPPER_CASE and _Private_Constant style bindings are census material."""
    if name.startswith('__'):
        return False
    if name.isupper():
        return True
    return name.startswith('_') and name[1:2].isupper()


def _occurrences(name: str) -> tuple[int, collections.Counter]:
    pattern = re.compile(r'\b' + re.escape(name) + r'\b')
    total = 0
    where: collections.Counter = collections.Counter()
    for path, text in TEXTS.items():
        hits = len(pattern.findall(text))
        if hits:
            total += hits
            where[_zone(path)] += hits
    return total, where


def _census() -> list[tuple[str, pathlib.Path, int, str, str]]:
    flags: list[tuple[str, pathlib.Path, int, str, str]] = []
    for path in FILES:
        if _zone(path) != 'src':
            continue
        for dotted, kind, lineno in _declarations(path):
            leaf = dotted.split('.')[-1]
            if leaf.startswith('__') or leaf == '__all__':
                continue
            total, where = _occurrences(leaf)
            external = total - where['src']
            if total <= 1:
                flags.append(('ORPHAN', path, lineno, kind, dotted))
            elif external == 0 and where['src'] <= 1:
                flags.append(('UNUSED-IN-SRC', path, lineno, kind, dotted))
    return flags


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description='Report src/ declarations that nothing references.')
    ap.add_argument('-q', '--quiet', action='store_true',
                    help='print only the tally line')
    args = ap.parse_args(argv)

    flags = _census()
    n_decl = sum(len(_declarations(p)) for p in FILES if _zone(p) == 'src')
    if not args.quiet:
        for cat, path, lineno, kind, name in flags:
            rel = path.relative_to(ROOT).as_posix()
            print(f'{cat:14} {rel}:{lineno}: {kind} {name}')
    print(f'{len(flags)} flags of {n_decl} declarations')
    return 1 if flags else 0


if __name__ == '__main__':
    sys.exit(main())
