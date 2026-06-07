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


def test_read_file_reads_workspace_file(tmp_path):
    # The agent writes phase scripts into the workspace and must be able to read
    # them back with a plain workspace-relative path (not the repo root).
    sess = _session(tmp_path)
    (tmp_path / "ws" / "1_build").mkdir(parents=True)
    (tmp_path / "ws" / "1_build" / "build.py").write_text("print('hi')\n")
    r = session_registry.execute(sess, "read_file", {"path": "1_build/build.py"})
    assert not r.is_error
    assert "print('hi')" in r.summary["value"]


def test_list_dir_lists_workspace_dir(tmp_path):
    sess = _session(tmp_path)
    (tmp_path / "ws" / "1_build").mkdir(parents=True)
    (tmp_path / "ws" / "1_build" / "build.py").write_text("x")
    r = session_registry.execute(sess, "list_dir", {"path": "1_build"})
    assert not r.is_error
    assert any(e["name"] == "build.py" for e in r.summary["value"])


def test_write_file_creates_file_and_parents(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(
        sess, "write_file", {"path": "1_build/build.py", "content": "print('hi')\n"})
    assert not r.is_error
    written = tmp_path / "ws" / "1_build" / "build.py"
    assert written.read_text() == "print('hi')\n"
    assert r.summary["bytes_written"] == len("print('hi')\n")


def test_write_file_rejects_path_escape(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(
        sess, "write_file", {"path": "../escape.py", "content": "x"})
    assert r.is_error
    assert "escapes" in r.error


def test_run_script_runs_and_reports_returncode(tmp_path):
    sess = _session(tmp_path)
    session_registry.execute(sess, "write_file", {
        "path": "make.py",
        "content": "open('out.txt','w').write('done')\nprint('ran')\n"})
    r = session_registry.execute(sess, "run_script", {"path": "make.py"})
    assert not r.is_error
    assert r.summary["returncode"] == 0
    assert "ran" in r.summary["stdout"]
    assert (tmp_path / "ws" / "out.txt").read_text() == "done"


def test_run_script_can_import_askslm(tmp_path):
    sess = _session(tmp_path)
    session_registry.execute(sess, "write_file", {
        "path": "imp.py", "content": "import askslm\nprint('ok')\n"})
    r = session_registry.execute(sess, "run_script", {"path": "imp.py"})
    assert not r.is_error
    assert r.summary["returncode"] == 0
    assert "ok" in r.summary["stdout"]


def test_run_script_rejects_non_python(tmp_path):
    sess = _session(tmp_path)
    (tmp_path / "ws" / "data.csv").write_text("a,b\n")
    r = session_registry.execute(sess, "run_script", {"path": "data.csv"})
    assert r.is_error


def test_run_script_rejects_path_outside_workspace(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(sess, "run_script", {"path": "../evil.py"})
    assert r.is_error
    assert "escapes" in r.error


def test_run_script_missing_file_errors(tmp_path):
    sess = _session(tmp_path)
    r = session_registry.execute(sess, "run_script", {"path": "nope.py"})
    assert r.is_error


def test_run_script_nonzero_exit_is_reported_not_raised(tmp_path):
    sess = _session(tmp_path)
    session_registry.execute(sess, "write_file", {
        "path": "boom.py", "content": "import sys\nprint('partial')\nsys.exit(3)\n"})
    r = session_registry.execute(sess, "run_script", {"path": "boom.py"})
    assert not r.is_error                      # the tool ran; the script's exit is data
    assert r.summary["returncode"] == 3
    assert "partial" in r.summary["stdout"]


def test_run_script_caps_stdout(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.tools.session_tools._SCRIPT_OUTPUT_CAP", 10)
    sess = _session(tmp_path)
    session_registry.execute(sess, "write_file", {
        "path": "loud.py", "content": "print('x' * 1000)\n"})
    r = session_registry.execute(sess, "run_script", {"path": "loud.py"})
    assert not r.is_error
    assert len(r.summary["stdout"]) <= 10
