import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from record_run import append_run
from schema import new_row


def test_append_run_writes_header_once_then_appends(tmp_path):
    csv_path = tmp_path / "index.csv"
    append_run(csv_path, new_row(question_id="q01", run_id="r1"))
    append_run(csv_path, new_row(question_id="q01", run_id="r2"))
    with csv_path.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert [row["run_id"] for row in rows] == ["r1", "r2"]


def test_append_run_rejects_incomplete_row(tmp_path):
    with pytest.raises(ValueError, match="question_id"):
        append_run(tmp_path / "index.csv", {"run_id": "r1"})
