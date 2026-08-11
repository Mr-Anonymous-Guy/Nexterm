"""Workspace scanning (SDD section 9)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import detectors, db

SKIP_DIRS = {
    "node_modules", ".git", "vendor", "target", "dist", "build",
    "__pycache__", ".venv", "venv", ".tox", ".mypy_cache",
}


def _walk(root: Path, max_depth: int):
    root = root.resolve()
    start_depth = len(root.parts)
    for path in [root, *root.rglob("*")]:
        if not path.is_dir():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        depth = len(path.parts) - start_depth
        if depth > max_depth:
            continue
        yield path


def full_scan(conn: sqlite3.Connection, roots: list[Path], max_depth: int = 4) -> dict:
    scanned = 0
    updated = 0
    seen_project_roots: set[Path] = set()
    for root in roots:
        root = Path(root).expanduser()
        if not root.exists():
            continue
        for directory in _walk(root, max_depth):
            # Skip subdirectories of an already-detected project root
            if any(directory.is_relative_to(p) and directory != p for p in seen_project_roots):
                continue
            scanned += 1
            if detectors.is_project_root(directory):
                facts = detectors.detect_all(directory)
                facts["last_indexed"] = db.now_iso()
                db.upsert_project(conn, facts)
                seen_project_roots.add(directory)
                updated += 1
    return {"scanned": scanned, "updated": updated}
