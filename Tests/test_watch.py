"""_new_phase_lines/_status_line/_elapsed are pure enough to unit test -- watch()
itself is a live terminal loop (polling squeue, sleeping, catching Ctrl-C),
verified by running it, the same convention session.py already uses. One
exception: the "job left the queue" exit condition is a real correctness
property (a job killed outside askslm never gets to write status.txt, so status
alone would hang the loop forever) worth locking down end to end."""
import time

from askslm.cli import jobs, watch


def test_no_phases_yet_prints_nothing():
    assert watch._new_phase_lines([], printed=set(), job_finished=False) == []


def test_a_completed_phase_prints_once_with_its_duration():
    events = [(100.0, "start", "discovering cohort"),
             (112.4, "start", "reading profile matrix")]

    lines = watch._new_phase_lines(events, printed=set(), job_finished=False)

    assert lines == ["[1/3] discovering cohort... 12.4s"]


def test_the_open_final_phase_is_not_printed_while_still_running():
    events = [(100.0, "start", "discovering cohort")]

    assert watch._new_phase_lines(events, printed=set(), job_finished=False) == []


def test_the_open_final_phase_is_printed_once_the_job_is_finished():
    events = [(100.0, "start", "discovering cohort")]

    lines = watch._new_phase_lines(events, printed=set(), job_finished=True)

    assert len(lines) == 1
    assert lines[0].startswith("[1/3] discovering cohort...")


def test_an_already_printed_phase_is_never_printed_again():
    events = [(100.0, "start", "discovering cohort"),
             (112.4, "start", "reading profile matrix")]

    lines = watch._new_phase_lines(events, printed={"discovering cohort"}, job_finished=False)

    assert lines == []


def test_status_line_shows_the_pending_reason_and_queued_time():
    line = watch._status_line("123", "PENDING", "Resources", submitted_at=0.0,
                              events=[], printed=set())

    assert "PENDING" in line
    assert "Resources" in line
    assert "queued" in line


def test_status_line_shows_the_running_phase_when_one_is_open():
    events = [(0.0, "start", "discovering cohort")]

    line = watch._status_line("123", "RUNNING", "None", submitted_at=0.0,
                              events=events, printed=set())

    assert "discovering cohort" in line
    assert "running" in line


def test_status_line_falls_back_to_bare_state_when_no_phase_is_open_yet():
    line = watch._status_line("123", "RUNNING", "None", submitted_at=0.0,
                              events=[], printed=set())

    assert line == "job 123 · RUNNING"


def test_elapsed_with_no_start_time_is_a_question_mark():
    assert watch._elapsed(None) == "?"


def test_elapsed_formats_minutes_and_seconds():
    assert watch._elapsed(time.time() - 125) == "2:05"


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
    monkeypatch.setattr(jobs, "squeue_state_and_reason", _job_already_gone)
    monkeypatch.setattr(watch.time, "sleep", _no_sleep)

    watch.watch(tmp_path, watch.Console(width=200))

    assert "killed outside askslm" in capsys.readouterr().out


def test_non_terminal_console_still_shows_periodic_progress(tmp_path, monkeypatch, capsys):
    """rich's console.status() is a transient Live display that writes nothing at
    all when the console isn't a real terminal -- a piped or logged session must
    still see periodic progress, not total silence."""
    calls = {"n": 0}

    def _pending_then_gone(job_id, run=None):
        calls["n"] += 1
        return ("PENDING", "Resources") if calls["n"] <= 2 else None

    def _no_sleep(seconds):
        pass

    jobs.write_job_id(tmp_path, "4213765")
    monkeypatch.setattr(jobs, "squeue_state_and_reason", _pending_then_gone)
    monkeypatch.setattr(watch.time, "sleep", _no_sleep)

    watch.watch(tmp_path, watch.Console(width=200, force_terminal=False))

    assert capsys.readouterr().out.count("PENDING") >= 2
