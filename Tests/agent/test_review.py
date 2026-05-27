import json
from Agents.review import analyze, format_report


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_counts_module_not_found_errors(tmp_path):
    log = tmp_path / "ws" / "results" / "agent_log"
    log.mkdir(parents=True)
    _write_jsonl(log / "s1.jsonl", [
        {"type": "tool_result", "tool_use_id": "u1", "is_error": True,
         "error": "ModuleNotFoundError: No module named 'biom'", "traceback": ""},
    ])
    _write_jsonl(log / "s2.jsonl", [
        {"type": "tool_result", "tool_use_id": "u1", "is_error": True,
         "error": "ModuleNotFoundError: No module named 'biom'", "traceback": ""},
        {"type": "tool_result", "tool_use_id": "u2", "is_error": True,
         "error": "ModuleNotFoundError: No module named 'biom'", "traceback": ""},
    ])
    result = analyze(tmp_path)
    assert result.module_not_found["biom"] == 3


def test_counts_successful_imports(tmp_path):
    log = tmp_path / "ws" / "results" / "agent_log"
    log.mkdir(parents=True)
    _write_jsonl(log / "s1.jsonl", [
        {"type": "tool_call", "tool": "run_python", "tool_use_id": "u1",
         "code": "import numpy", "imports_used": ["numpy"]},
        {"type": "tool_result", "tool_use_id": "u1", "is_error": False, "result_summary": {}},
    ])
    result = analyze(tmp_path)
    assert result.imports_used["numpy"] == 1


def test_clusters_recurring_snippets(tmp_path):
    log = tmp_path / "ws" / "results" / "agent_log"
    log.mkdir(parents=True)
    _write_jsonl(log / "s1.jsonl", [
        {"type": "tool_call", "tool": "run_python", "tool_use_id": "u1",
         "code": "x = matrix_1.relative.mean()", "imports_used": []},
    ])
    _write_jsonl(log / "s2.jsonl", [
        {"type": "tool_call", "tool": "run_python", "tool_use_id": "u1",
         "code": "y = matrix_2.relative.mean()", "imports_used": []},
    ])
    _write_jsonl(log / "s3.jsonl", [
        {"type": "tool_call", "tool": "run_python", "tool_use_id": "u1",
         "code": "z = matrix_1.relative.mean()", "imports_used": []},
    ])
    result = analyze(tmp_path)
    clusters = [c for c in result.snippet_clusters if c.count >= 3]
    assert len(clusters) == 1
    assert ".relative.mean()" in clusters[0].representative


def test_format_report_includes_both_sections(tmp_path):
    log = tmp_path / "ws" / "results" / "agent_log"
    log.mkdir(parents=True)
    _write_jsonl(log / "s1.jsonl", [
        {"type": "tool_result", "is_error": True, "tool_use_id":"u",
         "error": "ModuleNotFoundError: No module named 'foo'", "traceback":""},
    ])
    text = format_report(analyze(tmp_path))
    assert "Whitelist candidates" in text
    assert "Tool-promotion candidates" in text
