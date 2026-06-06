import pandas as pd
from agent.workspace import Workspace
from agent.session import Session
from agent.tools.session_tools import session_registry


def test_summarize_returns_handle_summary(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    sess = Session.start(Workspace.open(root))
    h = sess.variables.put(pd.DataFrame({"x": [1]}), hint="df")

    r = session_registry.execute(sess, "summarize", {"handle": h})
    assert not r.is_error
    assert r.summary["handle"] == h
    assert r.summary["type"] == "DataFrame"


def test_list_workspace_inputs_lists_files(tmp_path):
    root = tmp_path / "ws"; (root / "inputs").mkdir(parents=True)
    (root / "inputs" / "metadata.csv").write_text("acc\nS1\n")
    (root / "inputs" / "taxonomy.csv").write_text("acc,tax_id\nS1,1\n")
    sess = Session.start(Workspace.open(root))

    r = session_registry.execute(sess, "list_workspace_inputs", {})
    assert not r.is_error
    names = {f["name"] for f in r.summary["value"]}
    assert {"metadata.csv", "taxonomy.csv"} <= names


def _session(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    return Session.start(Workspace.open(root))


def test_read_file_reads_repo_file(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(sess, "read_file", {"path": "CLAUDE.md"})
    assert not r.is_error
    assert "Ask-SLM" in r.summary["value"]
    assert r.summary["truncated"] is False


def test_read_file_caps_size(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.tools.session_tools._READ_CAP_BYTES", 10)
    sess = _session(tmp_path)
    r = session_registry.execute(sess, "read_file", {"path": "CLAUDE.md"})
    assert not r.is_error
    assert len(r.summary["value"]) <= 10
    assert r.summary["truncated"] is True


def test_read_file_rejects_path_escape(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(sess, "read_file", {"path": "../../../../etc/passwd"})
    assert r.is_error
    assert "escapes" in r.error


def test_list_dir_lists_entries(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(sess, "list_dir", {"path": "Docs"})
    assert not r.is_error
    entries = r.summary["value"]
    assert entries                                          # Docs is non-empty
    assert any(e["name"].endswith(".html") for e in entries)


def test_read_file_missing_path_errors(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(sess, "read_file", {"path": "does/not/exist.txt"})
    assert r.is_error


def test_read_file_rejects_hidden_path(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(sess, "read_file", {"path": ".git/config"})
    assert r.is_error
    assert "hidden" in r.error
