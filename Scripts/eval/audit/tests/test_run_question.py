import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cohortquery.accession import Accession
from cohortquery.cohort import Cohort
from cohortquery.sources import Source
from cohortquery.translation import SourceQuery

from run_question import write_sidecars


def _cohort(**by_source_keys):
    by_source = {Source[name]: frozenset(Accession(key) for key in keys)
                 for name, keys in by_source_keys.items()}
    return Cohort(by_source=by_source)


def test_write_sidecars_writes_sql_and_resolved_biosamples(tmp_path):
    cohort = _cohort(SRA_METADATA=["SAMN001", "SAMN002"])
    queries = [SourceQuery(source=Source.SRA_METADATA, sql="SELECT biosample FROM sra_metadata")]
    run_dir = tmp_path / "runs" / "r1"

    row_counts = write_sidecars(cohort, queries, run_dir)

    assert row_counts["SRA_METADATA"] == 2
    sql_text = (run_dir / "generated.sql").read_text()
    assert "SRA_METADATA" in sql_text and "SELECT biosample FROM sra_metadata" in sql_text
    results_text = (run_dir / "results.csv").read_text()
    assert "source,biosample" in results_text
    assert "SRA_METADATA,SAMN001" in results_text


def test_write_sidecars_resolved_cohort_can_differ_from_raw_sql():
    """The actual bug this guards: raw native SQL and the resolved cohort are not
    the same set once jattr_criteria narrows or widens it -- a sidecar recording
    raw SQL execution instead of the resolved Cohort silently reports the wrong
    answer (this happened: 6.5M raw-SQL rows recorded for a question whose real,
    jattr-intersected cohort was 0)."""
    cohort = _cohort(SRA_METADATA=[])
    queries = [SourceQuery(source=Source.SRA_METADATA,
                            sql="SELECT biosample FROM sra_metadata WHERE librarysource = 'METAGENOMIC'",
                            sql_jattr_combinator="intersect")]
    run_dir = Path("/tmp/write_sidecars_resolved_test")

    row_counts = write_sidecars(cohort, queries, run_dir)

    assert row_counts["SRA_METADATA"] == 0


def test_write_sidecars_skips_none_sql_query(tmp_path):
    cohort = _cohort(SRA_METADATA=["SAMN001"], METALOG_METADATA=[])
    queries = [
        SourceQuery(source=Source.SRA_METADATA, sql="SELECT biosample FROM sra_metadata"),
        SourceQuery(source=Source.METALOG_METADATA, sql=None),
    ]
    run_dir = tmp_path / "runs" / "r1"

    row_counts = write_sidecars(cohort, queries, run_dir)

    assert row_counts["METALOG_METADATA"] == 0
    sql_text = (run_dir / "generated.sql").read_text()
    assert "None;" not in sql_text
    assert "METALOG_METADATA" in sql_text


def test_write_sidecars_handles_multiple_sources(tmp_path):
    cohort = _cohort(SRA_METADATA=["SAMN001"], METALOG_METADATA=["SAMN002"])
    queries = [
        SourceQuery(source=Source.SRA_METADATA, sql="SELECT biosample FROM sra_metadata"),
        SourceQuery(source=Source.METALOG_METADATA, sql="SELECT biosample FROM metalog_metadata"),
    ]
    run_dir = tmp_path / "runs" / "r1"

    row_counts = write_sidecars(cohort, queries, run_dir)

    assert row_counts["SRA_METADATA"] == 1
    assert row_counts["METALOG_METADATA"] == 1
    sql_text = (run_dir / "generated.sql").read_text()
    assert "SRA_METADATA" in sql_text and "SELECT biosample FROM sra_metadata" in sql_text
    assert "METALOG_METADATA" in sql_text and "SELECT biosample FROM metalog_metadata" in sql_text
    results_text = (run_dir / "results.csv").read_text()
    assert "SRA_METADATA,SAMN001" in results_text
    assert "METALOG_METADATA,SAMN002" in results_text
