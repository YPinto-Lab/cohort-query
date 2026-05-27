import json
from Agents.show import format_session


def test_format_session_renders_chronological(tmp_path):
    log = tmp_path / "s.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in [
        {"ts":"t1","type":"user","content":"hi"},
        {"ts":"t2","type":"tool_call","tool":"foo","args":{"a":1},"tool_use_id":"u1"},
        {"ts":"t3","type":"tool_result","tool_use_id":"u1","is_error":False,"result_summary":{"type":"DataFrame"},"latency_ms":12},
        {"ts":"t4","type":"assistant","content":"ok"},
    ]) + "\n")
    text = format_session(log)
    assert "You: hi" in text
    assert "foo(" in text
    assert "DataFrame" in text
    assert "Assistant: ok" in text
