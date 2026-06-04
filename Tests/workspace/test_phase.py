import pytest

from askslm import workspace


def _make_tree(tmp_path):
    root = tmp_path / "Workspaces" / "ABX"
    (root / "0_inputs").mkdir(parents=True)
    (root / "1_build").mkdir()
    (root / "2_transform" / "no-control_bacteria").mkdir(parents=True)
    (root / "3_analyze" / "no-control_bacteria" / "braycurtis").mkdir(parents=True)
    return root


def test_build_phase_resolves_inputs_and_result(tmp_path):
    root = _make_tree(tmp_path)

    ws = workspace.phase(root / "1_build" / "build.py")

    assert ws.name == "build"
    assert ws.inputs == root / "0_inputs"
    assert ws.result == root / "1_build"


def test_transform_result_is_result_subdir(tmp_path):
    root = _make_tree(tmp_path)

    ws = workspace.phase(root / "2_transform" / "no-control_bacteria" / "explore.py")

    assert ws.name == "transform"
    assert ws.result == root / "2_transform" / "no-control_bacteria" / "result"
    assert ws.result.is_dir()


def test_analyze_makes_data_and_plots(tmp_path):
    root = _make_tree(tmp_path)
    script = root / "3_analyze" / "no-control_bacteria" / "braycurtis" / "analysis.py"

    ws = workspace.phase(script)

    assert ws.name == "analyze"
    assert ws.data == script.parent / "data"
    assert ws.plots == script.parent / "plots"
    assert ws.data.is_dir() and ws.plots.is_dir()


def test_script_outside_workspaces_raises(tmp_path):
    loose = tmp_path / "loose" / "build.py"
    loose.parent.mkdir(parents=True)

    with pytest.raises(ValueError):
        workspace.phase(loose)


def test_unknown_phase_folder_raises(tmp_path):
    root = tmp_path / "Workspaces" / "ABX"
    (root / "9_weird").mkdir(parents=True)

    with pytest.raises(ValueError):
        workspace.phase(root / "9_weird" / "x.py")
