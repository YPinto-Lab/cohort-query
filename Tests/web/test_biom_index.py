from pathlib import Path

import numpy as np
from biom import Table

from web.biom_index import biom_tree


def _write_biom(path: Path, n_obs: int, n_samp: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.ones((n_obs, n_samp), dtype=float)
    obs = [f"f{i}" for i in range(n_obs)]
    samp = [f"S{i}" for i in range(n_samp)]
    path.write_text(Table(data, obs, samp).to_json("test"))


def test_tree_groups_biom_by_phase_with_shape(tmp_path):
    _write_biom(tmp_path / "1_build" / "feature_table.biom", 3, 4)
    _write_biom(tmp_path / "2_transform" / "no-control" / "result" / "feature_table.biom", 2, 4)
    _write_biom(tmp_path / "3_analyze" / "no-control" / "braycurtis" / "data" / "braycurtis.biom", 4, 4)

    tree = biom_tree(tmp_path)
    phases = {group.phase: group for group in tree}

    assert phases["build"].entries[0].rel_path == "1_build/feature_table.biom"
    assert phases["build"].entries[0].shape == (3, 4)
    assert phases["transform"].entries[0].label == "no-control"
    assert phases["analyze"].entries[0].rel_path.endswith("braycurtis.biom")


def test_tree_skips_phases_with_no_biom(tmp_path):
    _write_biom(tmp_path / "1_build" / "feature_table.biom", 1, 1)
    tree = biom_tree(tmp_path)
    assert [group.phase for group in tree] == ["build"]
