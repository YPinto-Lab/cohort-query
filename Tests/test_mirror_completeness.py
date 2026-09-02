"""A mirror missing its enrichment tables must be rejected at open time, not hours later.

`build_duckdb.py` builds seven of the eleven tables the package needs; attribute_keys,
schema_catalog and the two embedding tables come from three further scripts that were
for a long time run by hand. A mirror built by the documented command was therefore
silently missing the LLM's entire vocabulary, and the failure surfaced deep inside
discovery as a bare DuckDB "Table with name schema_catalog does not exist" -- after the
researcher had already typed a question and waited.
"""
import duckdb
import pytest

from askslm.adapters import (REQUIRED_TABLES, DuckDbConnection, IncompleteMirror,
                             missing_tables, verify_mirror)


def _mirror(path, tables):
    connection = duckdb.connect(str(path))
    for table in tables:
        connection.execute(f"CREATE TABLE {table} (x INTEGER)")
    connection.close()
    return path


def test_a_complete_mirror_passes(tmp_path):
    connection = DuckDbConnection(_mirror(tmp_path / "full.duckdb", REQUIRED_TABLES))

    verify_mirror(connection)      # must not raise

    assert missing_tables(connection._connection) == []
    connection.close()


def test_the_partial_mirror_build_duckdb_leaves_behind_is_rejected(tmp_path):
    """Exactly the seven tables build_duckdb.py creates -- the shape that shipped."""
    built_by_build_duckdb = {"sra_metadata", "sra_taxonomy", "stat_coverage",
                             "metalog_metadata", "metalog_metaphlan4",
                             "metalog_motus3", "metalog_spire_motus"}
    connection = DuckDbConnection(_mirror(tmp_path / "partial.duckdb", built_by_build_duckdb))

    with pytest.raises(IncompleteMirror) as raised:
        verify_mirror(connection, tmp_path / "partial.duckdb")

    message = str(raised.value)
    for table in ("attribute_keys", "schema_catalog",
                  "attribute_key_embeddings", "column_value_embeddings"):
        assert table in message
    assert "build_all.sh --stage enrich" in message      # the message says how to fix it
    connection.close()


def test_a_view_counts_as_present_just_like_a_table(tmp_path):
    """sra_metadata and sra_taxonomy are VIEWs over the sorted sidecars, not tables."""
    path = tmp_path / "views.duckdb"
    connection = duckdb.connect(str(path))
    for table in REQUIRED_TABLES - {"sra_metadata"}:
        connection.execute(f"CREATE TABLE {table} (x INTEGER)")
    connection.execute("CREATE VIEW sra_metadata AS SELECT 1 AS x")
    connection.close()

    assert missing_tables(duckdb.connect(str(path), read_only=True)) == []


def test_mirror_config_is_not_required(tmp_path):
    """A single-file mirror -- the generated test fixture -- records no sidecars and
    needs none, so demanding mirror_config would reject a perfectly usable database."""
    assert "mirror_config" not in REQUIRED_TABLES
    connection = DuckDbConnection(_mirror(tmp_path / "single.duckdb", REQUIRED_TABLES))

    verify_mirror(connection)

    connection.close()
