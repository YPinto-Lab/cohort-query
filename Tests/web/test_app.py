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
