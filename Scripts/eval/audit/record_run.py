"""Append-only writer for index.csv -- one row per verification run, never
overwritten in place, so a question's judgment history survives every
recheck (see the design doc's rationale for why this isn't a mutable snapshot)."""
from __future__ import annotations

import csv
from pathlib import Path

from schema import COLUMNS


def append_run(csv_path: Path, row: dict) -> None:
    missing = set(COLUMNS) - set(row)
    if missing:
        raise ValueError(f"row missing columns: {sorted(missing)}")
    is_new = not csv_path.exists()
    with csv_path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)
