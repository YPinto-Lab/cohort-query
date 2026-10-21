import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from schema import COLUMNS, new_row


def test_new_row_fills_all_columns_with_defaults():
    row = new_row(question_id="q01", question="stool samples from IBD adults")
    assert set(row.keys()) == set(COLUMNS)
    assert row["question_id"] == "q01"
    assert row["judgment"] == ""


def test_new_row_rejects_unknown_column():
    with pytest.raises(ValueError, match="foo"):
        new_row(foo="bar")
