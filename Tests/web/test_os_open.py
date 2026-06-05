from pathlib import Path

from web import os_open


def test_open_path_invokes_launcher_and_reports_ok(tmp_path, monkeypatch):
    target = tmp_path / "file.py"
    target.write_text("x")
    calls = []
    monkeypatch.setattr(os_open, "_launch", lambda p: calls.append(p))

    result = os_open.open_path(target)

    assert result["ok"] is True
    assert calls == [target]
    assert result["path"] == str(target)


def test_open_path_falls_back_to_path_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "file.py"
    target.write_text("x")

    def _boom(_p):
        raise OSError("no handler")

    monkeypatch.setattr(os_open, "_launch", _boom)

    result = os_open.open_path(target)

    assert result["ok"] is False
    assert result["path"] == str(target)
    assert "no handler" in result["error"]
