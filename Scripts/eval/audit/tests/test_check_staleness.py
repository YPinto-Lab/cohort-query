import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from check_staleness import find_stale
from schema import COLUMNS, new_row


def _write(csv_path, rows):
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_find_stale_flags_mirror_rebuild(tmp_path):
    csv_path = tmp_path / "index.csv"
    _write(csv_path, [new_row(question_id="q01", checked_at="2026-10-05T00:00:00",
                               verified_mirror_build="build-A", verified_code_commit="abc123")])
    stale = find_stale(csv_path, current_mirror_build="build-B", current_code_commit="abc123")
    assert len(stale) == 1
    assert stale[0].question_id == "q01"
    assert stale[0].reason == "mirror_rebuilt"


def test_find_stale_uses_only_the_latest_run_per_question(tmp_path):
    csv_path = tmp_path / "index.csv"
    _write(csv_path, [
        new_row(question_id="q01", checked_at="2026-10-05T00:00:00",
                verified_mirror_build="build-A", verified_code_commit="abc123"),
        new_row(question_id="q01", checked_at="2026-10-06T00:00:00",
                verified_mirror_build="build-B", verified_code_commit="abc123"),
    ])
    stale = find_stale(csv_path, current_mirror_build="build-B", current_code_commit="abc123")
    assert stale == []


def test_find_stale_reports_nothing_when_current(tmp_path):
    csv_path = tmp_path / "index.csv"
    _write(csv_path, [new_row(question_id="q01", checked_at="2026-10-05T00:00:00",
                               verified_mirror_build="build-A", verified_code_commit="abc123")])
    assert find_stale(csv_path, "build-A", "abc123") == []
