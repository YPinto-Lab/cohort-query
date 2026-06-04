from Clients.cli import main


def test_workspace_new_stamps_phase_tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    main(["workspace", "new", "ABX"])

    root = tmp_path / "Workspaces" / "ABX"
    assert (root / "0_inputs").is_dir()
    assert (root / "1_build" / "build.py").exists()
    assert (root / "2_transform" / "shared.py").exists()
    assert (root / "3_analyze" / "shared.py").exists()


def test_build_template_uses_workspace_import(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    main(["workspace", "new", "ABX"])

    build = (tmp_path / "Workspaces" / "ABX" / "1_build" / "build.py").read_text()
    assert "from askslm import workspace" in build
    assert "workspace.phase(__file__)" in build


def test_transform_add_creates_exploration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["workspace", "new", "ABX"])

    main(["transform", "add", "ABX", "no-control_bacteria"])

    explore = tmp_path / "Workspaces" / "ABX" / "2_transform" / "no-control_bacteria" / "explore.py"
    assert "ws.upstream()" in explore.read_text()


def test_analysis_add_creates_grouped_analysis(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["workspace", "new", "ABX"])
    main(["transform", "add", "ABX", "no-control_bacteria"])

    main(["analysis", "add", "ABX", "no-control_bacteria", "braycurtis"])

    analysis = (tmp_path / "Workspaces" / "ABX" / "3_analyze"
                / "no-control_bacteria" / "braycurtis" / "analysis.py")
    assert "ws.upstream()" in analysis.read_text()
