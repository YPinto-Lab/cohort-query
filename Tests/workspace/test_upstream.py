import numpy as np
import pytest
from biom import Table

from askslm import workspace


def _write_community(path):
    table = Table(np.array([[1.0, 2.0], [3.0, 4.0]]),
                  observation_ids=["a", "b"], sample_ids=["s1", "s2"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(table.to_json("test"))


def test_transform_upstream_is_build_community(tmp_path):
    root = tmp_path / "Workspaces" / "ABX"
    _write_community(root / "1_build" / "community.biom")
    script = root / "2_transform" / "no-control_bacteria" / "explore.py"
    script.parent.mkdir(parents=True)

    loaded = workspace.phase(script).upstream()

    assert loaded.shape == (2, 2)


def test_analyze_upstream_is_exploration_result(tmp_path):
    root = tmp_path / "Workspaces" / "ABX"
    _write_community(root / "2_transform" / "no-control_bacteria" / "result" / "community.biom")
    script = root / "3_analyze" / "no-control_bacteria" / "braycurtis" / "analysis.py"
    script.parent.mkdir(parents=True)

    loaded = workspace.phase(script).upstream()

    assert loaded.shape == (2, 2)


def test_build_upstream_raises(tmp_path):
    root = tmp_path / "Workspaces" / "ABX"
    script = root / "1_build" / "build.py"
    script.parent.mkdir(parents=True)

    with pytest.raises(ValueError):
        workspace.phase(script).upstream()


def test_shared_module_loads_phase_helpers(tmp_path):
    root = tmp_path / "Workspaces" / "ABX"
    (root / "2_transform").mkdir(parents=True)
    (root / "2_transform" / "shared.py").write_text("def cohort(table):\n    return table\n")
    script = root / "2_transform" / "no-control_bacteria" / "explore.py"
    script.parent.mkdir(parents=True)

    shared = workspace.phase(script).shared

    assert shared.cohort("x") == "x"
