"""The build's phase-by-phase progress trail: separate from log.txt (which
carries full ask()-phase SQL/LLM debug logging) so watch() can render
structured phase timing without replaying that backlog."""
from __future__ import annotations

import time
from pathlib import Path

PROGRESS_FILENAME = "progress.txt"
SUBMITTED_FILENAME = "submitted.txt"


def write_start(plan_dir: Path, label: str) -> None:
    path = plan_dir / PROGRESS_FILENAME
    with path.open("a") as handle:
        handle.write(f"{time.time()} start {label}\n")


def read_events(plan_dir: Path) -> list[tuple[float, str, str]]:
    path = plan_dir / PROGRESS_FILENAME
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        timestamp_text, event, label = line.split(" ", 2)
        events.append((float(timestamp_text), event, label))
    return events


def write_submitted(plan_dir: Path) -> None:
    (plan_dir / SUBMITTED_FILENAME).write_text(str(time.time()))


def read_submitted(plan_dir: Path) -> float | None:
    path = plan_dir / SUBMITTED_FILENAME
    return float(path.read_text()) if path.exists() else None
