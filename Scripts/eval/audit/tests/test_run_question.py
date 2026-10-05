import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "Tests"))
from fixtures.mirror import build_fixture_mirror

from cohortquery.adapters import DuckDbConnection
from cohortquery.sources import Source
from cohortquery.translation import SourceQuery

from run_question import write_sidecars


def test_write_sidecars_writes_sql_and_biosamples(tmp_path):
    mirror_path = build_fixture_mirror(tmp_path / "mirror.duckdb")
    connection = DuckDbConnection(mirror_path)
    queries = [SourceQuery(source=Source.SRA_METADATA, sql="SELECT biosample FROM sra_metadata")]
    run_dir = tmp_path / "runs" / "r1"

    row_counts = write_sidecars(connection, queries, run_dir)

    assert row_counts["SRA_METADATA"] > 0
    sql_text = (run_dir / "generated.sql").read_text()
    assert "SRA_METADATA" in sql_text and "SELECT biosample FROM sra_metadata" in sql_text
    results_text = (run_dir / "results.csv").read_text()
    assert "source,biosample" in results_text
    assert "SRA_METADATA," in results_text
