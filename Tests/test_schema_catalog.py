"""The schema catalog carries the values the LLM cannot guess.

The point of the catalog is that "IBD" must be matchable against the literal
strings actually stored in the data -- so the test that matters is that those
strings are present, and that a high-cardinality column does not drag them in.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "Scripts" / "build_mirror" / "steps"))
from step5_catalog_schema import SchemaCatalogBuilder

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


def test_an_identifier_column_ships_no_values():
    """Measured 2026-08-18: `jattr` had 39,065,549 distinct values in 39,100,115 rows and
    spent 119,263 chars -- 21% of the entire prompt -- listing 200 JSON blobs that teach
    the model nothing. A column whose distinct count approaches its row count is a key or
    free text, not a vocabulary."""
    builder = SchemaCatalogBuilder(Path("unused.duckdb"))

    assert builder._is_identifier(distinct_count=39_065_549, rows=39_100_115)
    assert not builder._is_identifier(distinct_count=271_406, rows=39_100_115)


def test_the_ratio_is_ignored_on_a_table_too_small_to_judge():
    """In a 20-row fixture a perfectly good 14-value vocabulary looks exactly like a
    primary key. Below the floor the ratio is noise, and applying it silently strips the
    values every test depends on."""
    builder = SchemaCatalogBuilder(Path("unused.duckdb"))

    assert not builder._is_identifier(distinct_count=14, rows=20)


def test_values_are_dropped_from_the_tail_until_they_fit_the_budget():
    """Cardinality alone does not bound size: 200 long free-text values cost more than
    20,000 short ones. Values arrive frequency-ordered, so the tail is the least useful."""
    builder = SchemaCatalogBuilder(Path("unused.duckdb"), max_value_chars=40)

    kept = json.loads(builder._within_budget([f"value-{n}" for n in range(50)]))

    assert len(kept) < 50
    assert kept[0] == "value-0"
    assert len(json.dumps(kept)) <= 40
