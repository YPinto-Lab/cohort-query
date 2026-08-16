"""The schema catalog carries the values the LLM cannot guess.

The point of the catalog is that "IBD" must be matchable against the literal
strings actually stored in the data -- so the test that matters is that those
strings are present, and that a high-cardinality column does not drag them in.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "Scripts" / "build_mirror"))

from build_schema_catalog import SchemaCatalogBuilder

from fixtures.mirror import build_fixture_mirror

import duckdb


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    path = build_fixture_mirror(tmp_path_factory.mktemp("catalog") / "fixture.duckdb")
    SchemaCatalogBuilder(path, max_distinct=5).build()
    connection = duckdb.connect(str(path), read_only=True)
    yield connection
    connection.close()


def _values(con, table, column):
    row = con.execute(
        "SELECT values_json FROM schema_catalog WHERE table_name = ? AND column_name = ?",
        [table, column],
    ).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def test_low_cardinality_column_ships_its_real_values(con):
    diseases = _values(con, "metalog_metadata", "subject_disease_status")

    assert diseases == ["Crohn's disease", "healthy control", "ulcerative colitis"]


def test_high_cardinality_column_ships_names_only(con):
    aliases = _values(con, "metalog_metadata", "sample_alias")

    assert aliases is None


def test_catalog_covers_both_metadata_tables_and_no_profile_table(con):
    tables = [row[0] for row in con.execute(
        "SELECT DISTINCT table_name FROM schema_catalog ORDER BY 1").fetchall()]

    assert tables == ["metalog_metadata", "sra_metadata"]


def test_every_column_is_catalogued_with_its_type(con):
    columns = con.execute("""
        SELECT count(*) FROM schema_catalog WHERE table_name = 'metalog_metadata'
    """).fetchone()[0]
    types = con.execute("""
        SELECT data_type FROM schema_catalog
        WHERE table_name = 'metalog_metadata' AND column_name = 'age_years'
    """).fetchone()[0]

    assert columns == 10
    assert types == "DOUBLE"


def test_distinct_count_is_recorded_even_when_values_are_omitted(con):
    count = con.execute("""
        SELECT distinct_count FROM schema_catalog
        WHERE table_name = 'metalog_metadata' AND column_name = 'sample_alias'
    """).fetchone()[0]

    assert count == 14
