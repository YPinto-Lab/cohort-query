"""Detect which workspace files an agent turn created or modified.

Pure functions: snapshot {relative-path: mtime} before a turn, snapshot again
after, diff into a list tagged by file kind. Decoupled from HOW the agent writes
files — it only observes the filesystem.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChangedFile:
    path: str   # workspace-relative, forward slashes
    kind: str   # "py" | "biom" | "other"


def snapshot(root: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in root.rglob("*"):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = p.stat().st_mtime
    return out


def diff(before: dict[str, float], after: dict[str, float]) -> list[ChangedFile]:
    changed: list[ChangedFile] = []
    for path, mtime in sorted(after.items()):
        if before.get(path) != mtime:
            changed.append(ChangedFile(path, _kind(path)))
    return changed


def _kind(path: str) -> str:
    if path.endswith(".biom"):
        return "biom"
    if path.endswith(".py"):
        return "py"
    return "other"
