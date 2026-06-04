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
