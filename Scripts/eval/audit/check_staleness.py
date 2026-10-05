"""Flags questions whose most recent verification run no longer matches the
current mirror build or code commit. Only reports -- re-verification is
always a deliberate action (append_run with the matching trigger_reason),
never an automatic overwrite."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StaleQuestion:
    question_id: str
    reason: str   # "mirror_rebuilt" / "code_changed" / "both"


def find_stale(csv_path: Path, current_mirror_build: str, current_code_commit: str
               ) -> list[StaleQuestion]:
    stale = []
    for question_id, row in _latest_run_per_question(csv_path).items():
        mirror_changed = row["verified_mirror_build"] != current_mirror_build
        code_changed = row["verified_code_commit"] != current_code_commit
        if mirror_changed and code_changed:
            stale.append(StaleQuestion(question_id, "both"))
        elif mirror_changed:
            stale.append(StaleQuestion(question_id, "mirror_rebuilt"))
        elif code_changed:
            stale.append(StaleQuestion(question_id, "code_changed"))
    return stale


def _latest_run_per_question(csv_path: Path) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    with csv_path.open() as fh:
        for row in csv.DictReader(fh):
            existing = latest.get(row["question_id"])
            # checked_at is ISO8601 (YYYY-MM-DDTHH:MM:SS), lexicographically sortable
            if existing is None or row["checked_at"] > existing["checked_at"]:
                latest[row["question_id"]] = row
    return latest
