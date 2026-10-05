"""progress.txt/submitted.txt are the worker's structured phase trail -- separate
from log.txt's full SQL/LLM debug logging, so watch() can render clean progress
without replaying that backlog."""
import time

from cohortquery.cli import progress


def test_write_start_appends_a_timestamped_event(tmp_path):
    progress.write_start(tmp_path, "discovering cohort")
    progress.write_start(tmp_path, "reading profile matrix")

    events = progress.read_events(tmp_path)

    assert [label for _, _, label in events] == [
        "discovering cohort", "reading profile matrix"]
    assert all(event == "start" for _, event, _ in events)
    assert events[0][0] <= events[1][0]           # timestamps in order


def test_read_events_with_no_file_yet_is_empty(tmp_path):
    assert progress.read_events(tmp_path) == []


def test_submitted_time_round_trips(tmp_path):
    progress.write_submitted(tmp_path)

    submitted = progress.read_submitted(tmp_path)

    assert submitted is not None
    assert submitted <= time.time()


def test_read_submitted_with_no_file_yet_is_none(tmp_path):
    assert progress.read_submitted(tmp_path) is None
