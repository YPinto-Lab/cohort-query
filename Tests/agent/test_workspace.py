import pytest
from agent.workspace import Workspace


def test_paths_resolve_relative_to_root(tmp_path):
    root = tmp_path / "ABX"
    (root / "inputs").mkdir(parents=True)
    ws = Workspace.open(root)
    assert ws.name == "ABX"
    assert ws.inputs_dir == root / "inputs"
    assert ws.results_dir == root / "results"
    assert ws.agent_log_dir == root / "results" / "agent_log"


def test_open_creates_agent_log_dir(tmp_path):
    root = tmp_path / "ABX"
    root.mkdir()
    ws = Workspace.open(root)
    assert ws.agent_log_dir.is_dir()


def test_missing_root_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Workspace.open(tmp_path / "nope")
