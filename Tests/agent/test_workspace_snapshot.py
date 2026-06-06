from agent.workspace import Workspace
from agent.workspace_snapshot import WorkspaceSnapshot


def test_snapshot_lists_files_and_inlines_md(tmp_path):
    root = tmp_path / "study"
    (root / "1_build").mkdir(parents=True)
    (root / "1_build" / "build.py").write_text("x = 1\n")
    (root / "1_build" / "build.md").write_text("the intent")
    (root / "0_inputs").mkdir()
    (root / "0_inputs" / "taxonomy.csv").write_text("a,b\n1,2\n")

    out = WorkspaceSnapshot(Workspace.open(root)).render()

    assert "study" in out
    assert "1_build/build.py" in out
    assert "0_inputs/taxonomy.csv" in out
    assert "the intent" in out      # .md inlined
    assert "a,b" not in out         # csv contents NOT read


def test_snapshot_skips_results_and_pycache(tmp_path):
    root = tmp_path / "study"
    root.mkdir()
    ws = Workspace.open(root)        # creates results/agent_log
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_text("junk")

    out = WorkspaceSnapshot(ws).render()

    assert "agent_log" not in out
    assert "x.pyc" not in out
