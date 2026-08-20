"""Only _new_lines is pure enough to unit test -- watch() itself is a live terminal
loop (polling squeue, sleeping, catching Ctrl-C), verified by running it, the same
convention session.py already uses. One exception: the "job left the queue" exit
condition is a real correctness property (a job killed outside askslm never gets to
write status.txt, so status alone would hang the loop forever) worth locking down."""
from askslm.cli import jobs, watch
from askslm.cli.watch import _new_lines


def test_no_log_file_yet_returns_no_lines(tmp_path):
    assert _new_lines(tmp_path / "log.txt", seen=0) == []


def test_returns_only_lines_not_seen_before(tmp_path):
    log_path = tmp_path / "log.txt"
    log_path.write_text("one\ntwo\nthree\n")

    assert _new_lines(log_path, seen=1) == ["two", "three"]


def test_watch_stops_once_squeue_says_the_job_is_gone_even_if_status_still_says_running(
        tmp_path, monkeypatch, capsys):
    """A job killed by `scancel` from outside askslm, or OOM-killed, dies before its
    finally block can write DONE/FAILED -- status.txt is stuck at RUNNING forever.
    squeue leaving the queue is the only signal guaranteed to update, so it alone
    must end the loop."""
    def _job_already_gone(job_id, run=None):
        return None

    def _no_sleep(seconds):
        pass

    jobs.write_job_id(tmp_path, "4213765")
    jobs.write_status(tmp_path, "RUNNING")
    monkeypatch.setattr(jobs, "squeue_state", _job_already_gone)
    monkeypatch.setattr(watch.time, "sleep", _no_sleep)

    watch.watch(tmp_path, watch.Console(width=200))

    assert "killed outside askslm" in capsys.readouterr().out
