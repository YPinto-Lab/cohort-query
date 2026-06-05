import pandas as pd
from fastapi.testclient import TestClient


def _ws(tmp_path):
    root = tmp_path / "ABX"; (root / "inputs").mkdir(parents=True)
    pd.DataFrame({"acc": ["S1"]}).to_csv(root / "inputs" / "metadata.csv", index=False)
    return root


def test_index_lists_workspaces(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/")
    assert r.status_code == 200
    assert "ABX" in r.text


def test_chat_page_renders(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX")
    assert r.status_code == 200
    assert "ABX" in r.text


def test_sse_streams_events_with_fake_llm(tmp_path, monkeypatch):
    from web import app as app_mod
    from agent.llm_client import FakeLLMClient, AssistantText
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    monkeypatch.setattr(app_mod, "build_llm", lambda: FakeLLMClient([[AssistantText(text="hi")]]))
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    client.get("/w/ABX")
    r = client.post("/w/ABX/messages", data={"message": "hello"})
    assert r.status_code == 200
    body = r.text
    assert "assistant_final" in body
    assert "hi" in body


def test_sessions_listing_shows_past_transcripts(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    root = _ws(tmp_path)
    (root / "results" / "agent_log").mkdir(parents=True)
    (root / "results" / "agent_log" / "20260526T120000-abc123.jsonl").write_text(
        '{"ts":"2026-05-26T12:00:00Z","type":"user","content":"hi"}\n'
    )
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX/sessions")
    assert r.status_code == 200
    assert "20260526T120000-abc123" in r.text


def test_replay_renders_transcript(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    root = _ws(tmp_path)
    (root / "results" / "agent_log").mkdir(parents=True)
    sid = "20260526T120000-abc123"
    (root / "results" / "agent_log" / f"{sid}.jsonl").write_text(
        '{"ts":"2026-05-26T12:00:00Z","type":"user","content":"hi"}\n'
        '{"ts":"2026-05-26T12:00:01Z","type":"assistant","content":"hello!"}\n'
    )
    client = TestClient(app_mod.app)
    r = client.get(f"/w/ABX/sessions/{sid}")
    assert r.status_code == 200
    assert "hi" in r.text and "hello!" in r.text


def test_workspace_path_traversal_is_rejected(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    # Encoded ".." segment escapes WORKSPACES_ROOT — must 404.
    r = client.get("/w/%2E%2E")
    assert r.status_code == 404


def test_session_id_path_traversal_is_rejected(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    root = _ws(tmp_path)
    (root / "results" / "agent_log").mkdir(parents=True)
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX/sessions/%2E%2E%2Fsecret")
    assert r.status_code == 404


def test_create_workspace_scaffolds_and_redirects(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    client = TestClient(app_mod.app)

    r = client.post("/workspaces", data={"name": "NewStudy"}, follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/w/NewStudy"
    assert (tmp_path / "NewStudy" / "1_build" / "build.py").is_file()


def test_create_workspace_rejects_existing(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    (tmp_path / "Existing").mkdir()
    client = TestClient(app_mod.app)
    r = client.post("/workspaces", data={"name": "Existing"})
    assert r.status_code == 400


def test_create_workspace_rejects_unsafe_name(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    client = TestClient(app_mod.app)
    r = client.post("/workspaces", data={"name": "../escape"})
    assert r.status_code == 400
    assert not (tmp_path.parent / "escape").exists()


def _ws_with_biom(tmp_path):
    import numpy as np
    from biom import Table
    root = tmp_path / "ABX"
    (root / "1_build").mkdir(parents=True)
    data = np.array([[0, 12, 3], [5, 0, 9]], dtype=float)
    table = Table(data, ["f1", "f2"], ["S1", "S2", "S3"],
                  observation_metadata=[{"name": "Bacteria"}, {"name": "E. coli"}],
                  sample_metadata=[{"subject": "A"}, {"subject": "B"}, {"subject": "C"}])
    (root / "1_build" / "feature_table.biom").write_text(table.to_json("t"))
    return root


def test_biom_table_counts_fragment_renders_cells_and_banner(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws_with_biom(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX/biom/table",
                   params={"path": "1_build/feature_table.biom", "tab": "counts"})
    assert r.status_code == 200
    assert "f1" in r.text and "S1" in r.text and "12" in r.text
    assert "of 2" in r.text  # banner mentions total features


def test_biom_table_rejects_path_outside_workspace(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws_with_biom(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX/biom/table",
                   params={"path": "../secret.biom", "tab": "counts"})
    assert r.status_code == 404


def test_biom_table_samples_tab_renders_metadata(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws_with_biom(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX/biom/table",
                   params={"path": "1_build/feature_table.biom", "tab": "samples"})
    assert r.status_code == 200
    assert "subject" in r.text and "S1" in r.text


def test_biom_shell_shows_tabs_tree_and_initial_table(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws_with_biom(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX/biom", params={"path": "1_build/feature_table.biom"})
    assert r.status_code == 200
    assert "Counts" in r.text and "Samples" in r.text and "Lineage" in r.text
    assert "feature_table" in r.text          # tree entry
    assert "12" in r.text                       # initial counts table rendered inline


def test_messages_appends_files_changed_block(tmp_path, monkeypatch):
    from web import app as app_mod
    from agent.llm_client import FakeLLMClient, AssistantText
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    monkeypatch.setattr(app_mod, "build_llm",
                        lambda: FakeLLMClient([[AssistantText(text="done")]]))
    _ws(tmp_path)

    # Simulate a file appearing during the turn: snapshot() (bound in app via
    # `from web.workspace_diff import snapshot`) returns empty before, one file after.
    snapshots = iter([{}, {"1_build/build.py": 1.0}])
    monkeypatch.setattr(app_mod, "snapshot", lambda _root: next(snapshots))

    client = TestClient(app_mod.app)
    client.get("/w/ABX")
    r = client.post("/w/ABX/messages", data={"message": "build it"})
    assert r.status_code == 200
    assert "files changed" in r.text.lower()
    assert "build.py" in r.text


def test_open_route_rejects_path_outside_workspace(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    r = client.post("/w/ABX/open", data={"path": "../../etc/passwd"})
    assert r.status_code == 404


def test_open_route_opens_file_inside_workspace(tmp_path, monkeypatch):
    from web import app as app_mod
    from web import os_open
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    root = _ws(tmp_path)
    (root / "1_build").mkdir(parents=True, exist_ok=True)
    (root / "1_build" / "build.py").write_text("x")
    monkeypatch.setattr(os_open, "_launch", lambda p: None)
    client = TestClient(app_mod.app)
    r = client.post("/w/ABX/open", data={"path": "1_build/build.py"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_home_has_create_form_and_cards(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/")
    assert r.status_code == 200
    assert 'action="/workspaces"' in r.text   # create form
    assert "ABX" in r.text                       # workspace card


def test_messages_html_events_are_json_encoded(tmp_path, monkeypatch):
    import json as _json
    from web import app as app_mod
    from agent.llm_client import FakeLLMClient, AssistantText
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    monkeypatch.setattr(app_mod, "build_llm",
                        lambda: FakeLLMClient([[AssistantText(text="hi")]]))
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    client.get("/w/ABX")
    r = client.post("/w/ABX/messages", data={"message": "hello"})
    html_blocks = [b for b in r.text.split("\n\n") if "event: html" in b]
    assert html_blocks  # at least one html fragment streamed
    for block in html_blocks:
        data_line = [l for l in block.splitlines() if l.startswith("data:")][0]
        payload = _json.loads(data_line[len("data:"):])  # must be valid single-line JSON
        assert isinstance(payload, str)


def test_chat_page_has_two_panes(tmp_path, monkeypatch):
    from web import app as app_mod
    monkeypatch.setattr(app_mod, "WORKSPACES_ROOT", tmp_path)
    _ws(tmp_path)
    client = TestClient(app_mod.app)
    r = client.get("/w/ABX")
    assert r.status_code == 200
    assert 'id="log"' in r.text and 'id="data-pane"' in r.text
    assert "Open workspace folder" in r.text
