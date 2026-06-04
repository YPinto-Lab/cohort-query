"""Enumerate a workspace's .biom outputs, grouped by phase, for the viewer tree.

build -> 1_build/feature_table.biom
transform -> 2_transform/<exploration>/result/feature_table.biom
analyze -> 3_analyze/<exploration>/<analysis>/data/*.biom
Shape comes from the biom JSON header (cheap), not a full table load.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

_PHASE_DIRS = [("1_build", "build"), ("2_transform", "transform"), ("3_analyze", "analyze")]


@dataclass(frozen=True)
class BiomEntry:
    label: str           # human label (exploration / analysis / file stem)
    rel_path: str        # workspace-relative, forward slashes
    shape: tuple[int, int]   # (features, samples)


@dataclass(frozen=True)
class BiomGroup:
    phase: str
    entries: list[BiomEntry]


def biom_tree(root: Path) -> list[BiomGroup]:
    groups: list[BiomGroup] = []
    for folder, phase in _PHASE_DIRS:
        phase_dir = root / folder
        if not phase_dir.is_dir():
            continue
        entries = [_entry(root, p) for p in sorted(phase_dir.rglob("*.biom"))]
        if entries:
            groups.append(BiomGroup(phase=phase, entries=entries))
    return groups


def _entry(root: Path, path: Path) -> BiomEntry:
    rel = path.relative_to(root)
    shape = _shape(path)
    return BiomEntry(label=_label(rel), rel_path=rel.as_posix(), shape=shape)


def _label(rel: Path) -> str:
    # transform/analyze: name the exploration; otherwise the file stem.
    parts = rel.parts
    if parts[0] == "2_transform" and len(parts) >= 2:
        return parts[1]
    if parts[0] == "3_analyze" and len(parts) >= 3:
        return f"{parts[1]} · {parts[2]}"
    return rel.stem


def _shape(path: Path) -> tuple[int, int]:
    try:
        shape = json.loads(path.read_text())["shape"]
        return (int(shape[0]), int(shape[1]))
    except Exception:
        return (0, 0)
