"""The schema catalog carries the values the LLM cannot guess.

The point of the catalog is that "IBD" must be matchable against the literal
strings actually stored in the data -- so the test that matters is that those
strings are present, and that a high-cardinality column does not drag them in.
"""
import json

import pytest

from fixtures.mirror import build_fixture_mirror

import duckdb


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    # build_fixture_mirror builds its own schema_catalog with max_distinct=5 (see
    # Tests/fixtures/mirror.py) -- the cutoff the truncation tests below assert against.
    path = build_fixture_mirror(tmp_path_factory.mktemp("catalog") / "fixture.duckdb")
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


def test_high_cardinality_column_ships_the_top_n_and_says_it_is_truncated(con):
    """It used to ship nothing, which left the model guessing at organism (~247k in real
    SRA). Top-N plus an explicit flag is enough, because the model is told to use ILIKE."""
    aliases = _values(con, "metalog_metadata", "sample_alias")
    truncated, distinct = con.execute("""
        SELECT truncated, distinct_count FROM schema_catalog
        WHERE table_name = 'metalog_metadata' AND column_name = 'sample_alias'
    """).fetchone()

    assert truncated is True
    assert distinct == 14
    assert aliases is not None and len(aliases) == 5      # the max_distinct of this fixture


def test_an_array_column_ships_its_ELEMENTS_and_records_its_type(con):
    """geo_loc_name_sam is VARCHAR[]. Its vocabulary is the countries inside the arrays,
    and the model needs the type to know it must use list_contains(), not =."""
    countries = _values(con, "sra_metadata", "geo_loc_name_sam")
    data_type = con.execute("""
        SELECT data_type FROM schema_catalog
        WHERE table_name = 'sra_metadata' AND column_name = 'geo_loc_name_sam'
    """).fetchone()[0]

    assert data_type.endswith("[]")
    assert "Germany" in countries                          # an element, not a stringified array
    assert not any(value.startswith("[") for value in countries)


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
