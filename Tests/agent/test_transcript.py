import json
from agent.transcript import TranscriptWriter


def test_writes_user_message(tmp_path):
    w = TranscriptWriter(tmp_path / "t.jsonl")
    w.user("hi")
    lines = [json.loads(l) for l in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert lines[0]["type"] == "user"
    assert lines[0]["content"] == "hi"
    assert "ts" in lines[0]


def test_writes_tool_call_and_result_pair(tmp_path):
    w = TranscriptWriter(tmp_path / "t.jsonl")
    w.tool_call("run_python", {"code": "feature_table.shape"}, tool_use_id="u1")
    w.tool_result_ok("u1", {"type": "FeatureTable"}, latency_ms=12)
    lines = [json.loads(l) for l in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert lines[0]["type"] == "tool_call"
    assert lines[0]["tool"] == "run_python"
    assert lines[1]["type"] == "tool_result"
    assert lines[1]["is_error"] is False
    assert lines[1]["latency_ms"] == 12


def test_writes_tool_error(tmp_path):
    w = TranscriptWriter(tmp_path / "t.jsonl")
    w.tool_result_err("u1", "boom", "Traceback...", latency_ms=3)
    line = json.loads((tmp_path / "t.jsonl").read_text().splitlines()[0])
    assert line["is_error"] is True
    assert line["error"] == "boom"


def test_run_python_call_includes_code_and_imports(tmp_path):
    w = TranscriptWriter(tmp_path / "t.jsonl")
    w.tool_call(
        "run_python",
        {"code": "import skbio\nx = 1"},
        tool_use_id="u1",
        code="import skbio\nx = 1",
        imports_used=["skbio"],
    )
    line = json.loads((tmp_path / "t.jsonl").read_text().splitlines()[0])
    assert line["code"] == "import skbio\nx = 1"
    assert line["imports_used"] == ["skbio"]
