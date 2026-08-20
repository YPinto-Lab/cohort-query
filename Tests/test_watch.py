"""Only _new_lines is pure enough to unit test -- watch() itself is a live terminal
loop (polling squeue, sleeping, catching Ctrl-C), verified by running it, the same
convention session.py already uses."""
from askslm.cli.watch import _new_lines


def test_no_log_file_yet_returns_no_lines(tmp_path):
    assert _new_lines(tmp_path / "log.txt", seen=0) == []


def test_returns_only_lines_not_seen_before(tmp_path):
    log_path = tmp_path / "log.txt"
    log_path.write_text("one\ntwo\nthree\n")

    assert _new_lines(log_path, seen=1) == ["two", "three"]
