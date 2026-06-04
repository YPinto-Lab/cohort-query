import pandas as pd
from agent.workspace import Workspace
from agent.session import Session


def test_session_creates_transcript_in_workspace(tmp_path):
    root = tmp_path / "ABX"
    root.mkdir()
    ws = Workspace.open(root)
    sess = Session.start(ws)
    assert sess.workspace is ws
    assert sess.transcript.path.parent == ws.agent_log_dir
    assert sess.transcript.path.suffix == ".jsonl"
    assert sess.messages == []


def test_session_put_and_get_handle(tmp_path):
    root = tmp_path / "ABX"; root.mkdir()
    ws = Workspace.open(root)
    sess = Session.start(ws)
    h = sess.variables.put(pd.DataFrame({"x": [1]}), hint="df")
    assert h == "df_1"
    assert sess.variables.get(h) is not None


def test_session_id_is_transcript_stem(tmp_path):
    root = tmp_path / "ABX"; root.mkdir()
    ws = Workspace.open(root)
    sess = Session.start(ws)
    assert sess.id == sess.transcript.path.stem
