"""The SLURM job runs this. No LLM, no session -- just plan.json + a mirror in,
biom and status files out."""
import pytest

import cohortquery
from cohortquery.adapters import CannedLlmBackend, DuckDbConnection
from cohortquery.cli import progress, worker
from cohortquery.translation import SourceQuery, Translation

from fixtures.mirror import build_fixture_mirror

TRANSLATION = Translation(
    interpretation="gut metagenomes",
    queries=(SourceQuery(cohortquery.Source.METALOG_METADATA,
                         "SELECT * FROM metalog_metadata"),))


def test_main_builds_the_biom_and_reports_success(tmp_path):
    db_path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(db_path)
    cohortquery.config(db=db_path, database=connection, backend=CannedLlmBackend(TRANSLATION))
    plan = cohortquery.ask("gut metagenomes")
    plan_dir = tmp_path / "plans" / "20260820_000000"
    plan_dir.mkdir(parents=True)
    plan.save(plan_dir / "plan.json")
    connection.close()

    worker.main([
        "--plan-dir", str(plan_dir), "--plan", str(plan_dir / "plan.json"),
        "--sources", "METALOG_MOTUS3", "--out", str(plan_dir / "cohort.biom"),
        "--db", str(db_path)])

    assert (plan_dir / "cohort.biom").exists()
    assert (plan_dir / "status.txt").read_text() == "DONE"
    assert "family" in (plan_dir / "report.txt").read_text()
    log_text = (plan_dir / "log.txt").read_text()
    assert "discovering cohort" in log_text
    assert "reading profile matrix" in log_text

    # ask() now discovers and caches the cohort onto the plan, so run() reuses it.
    progress_labels = [label for _, _, label in progress.read_events(plan_dir)]
    assert progress_labels == ["discovering cohort (cached)", "reading profile matrix",
                               "assembling and writing biom"]


def test_main_reports_failed_status_on_error(tmp_path):
    db_path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(db_path)
    cohortquery.config(db=db_path, database=connection, backend=CannedLlmBackend(TRANSLATION))
    plan = cohortquery.ask("gut metagenomes")
    plan_dir = tmp_path / "plans" / "20260820_000001"
    plan_dir.mkdir(parents=True)
    plan.save(plan_dir / "plan.json")
    connection.close()

    with pytest.raises(ValueError):
        worker.main([
            "--plan-dir", str(plan_dir), "--plan", str(plan_dir / "plan.json"),
            "--sources", "METALOG_MOTUS3", "--out", str(plan_dir / "cohort.biom"),
            "--db", str(tmp_path / "does_not_exist.duckdb")])

    assert (plan_dir / "status.txt").read_text() == "FAILED"
