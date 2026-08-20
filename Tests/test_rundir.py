"""One plan folder per question, created immediately -- and the log handler that
makes every SQL/LLM call inside it land in that folder's log.txt."""
import logging

from askslm.cli import rundir


def test_new_plan_dir_is_timestamped_and_already_created(tmp_path):
    plan_dir = rundir.new_plan_dir(root=tmp_path)

    assert plan_dir.parent == tmp_path
    assert plan_dir.exists()
    assert len(plan_dir.name) == 15                # YYYYMMDD_HHMMSS


def test_attached_handler_captures_askslm_logger_records(tmp_path):
    plan_dir = rundir.new_plan_dir(root=tmp_path)
    handler = rundir.attach_log_handler(plan_dir)

    logging.getLogger("askslm.adapters").info("hello from a query")
    rundir.detach_log_handler(handler)

    assert "hello from a query" in (plan_dir / "log.txt").read_text()


def test_detached_handler_no_longer_receives_records(tmp_path):
    plan_dir = rundir.new_plan_dir(root=tmp_path)
    handler = rundir.attach_log_handler(plan_dir)
    rundir.detach_log_handler(handler)

    logging.getLogger("askslm.adapters").info("should not appear")

    assert (plan_dir / "log.txt").read_text() == ""
