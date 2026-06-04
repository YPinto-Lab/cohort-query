from pathlib import Path

import numpy as np
from biom import Table

from web.biom_view import counts_window, samples_window, lineage_window


def _fixture_biom(path: Path) -> Path:
    data = np.array([
        [0, 12, 3, 0, 5],
        [5, 0, 9, 1, 0],
        [0, 7, 1, 0, 2],
    ], dtype=float)
    obs_ids = ["f1", "f2", "f3"]
    sample_ids = ["S1", "S2", "S3", "S4", "S5"]
    obs_md = [
        {"name": "Bacteria", "rank": "domain", "lineage": [1, 2]},
        {"name": "Firmicutes", "rank": "phylum", "lineage": [1, 2, 3]},
        {"name": "E. coli", "rank": "species", "lineage": [1, 2, 4]},
    ]
    sample_md = [
        {"subject": "A", "day": 1},
        {"subject": "A", "day": 2},
        {"subject": "B", "day": 1},
        {"subject": "B", "day": 2},
        {"subject": "C", "day": 1},
    ]
    table = Table(data, obs_ids, sample_ids,
                  observation_metadata=obs_md, sample_metadata=sample_md)
    path.write_text(table.to_json("test"))
    return path


def test_counts_window_full(tmp_path):
    p = _fixture_biom(tmp_path / "t.biom")
    w = counts_window(p)
    assert w.index == ["f1", "f2", "f3"]
    assert w.columns == ["S1", "S2", "S3", "S4", "S5"]
    assert w.rows[0] == [0, 12, 3, 0, 5]
    assert w.total_rows == 3 and w.total_cols == 5


def test_counts_window_paginates_rows_and_cols(tmp_path):
    p = _fixture_biom(tmp_path / "t.biom")
    w = counts_window(p, row_off=1, col_off=2, row_page=1, col_page=2)
    assert w.index == ["f2"]
    assert w.columns == ["S3", "S4"]
    assert w.rows == [[9, 1]]
    assert w.row_offset == 1 and w.col_offset == 2
    assert w.total_rows == 3 and w.total_cols == 5


def test_samples_window_is_metadata_table(tmp_path):
    p = _fixture_biom(tmp_path / "t.biom")
    w = samples_window(p)
    assert w.index == ["S1", "S2", "S3", "S4", "S5"]
    assert "subject" in w.columns and "day" in w.columns
    assert w.total_rows == 5


def test_lineage_window_is_feature_metadata_table(tmp_path):
    p = _fixture_biom(tmp_path / "t.biom")
    w = lineage_window(p)
    assert w.index == ["f1", "f2", "f3"]
    assert "name" in w.columns and "rank" in w.columns
    name_col = w.columns.index("name")
    assert w.rows[0][name_col] == "Bacteria"
