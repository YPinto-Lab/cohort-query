"""A mirror missing its enrichment tables must be rejected at open time, not hours later.

`step3_assemble_mirror.py` builds seven of the ten tables the package needs; schema_catalog,
the two attribute indexes and column_value_embeddings come from three further scripts that
were for a long time run by hand. A mirror built by the documented command was therefore
silently missing the LLM's entire vocabulary, and the failure surfaced deep inside
discovery as a bare DuckDB "Table with name schema_catalog does not exist" -- after the
researcher had already typed a question and waited.
"""
import duckdb
import pandas as pd
import pytest

from askslm.adapters import (REQUIRED_LANCE_TABLES, REQUIRED_TABLES, DuckDbConnection,
                             IncompleteMirror, missing_tables, verify_mirror)


def _mirror(path, tables):
    connection = duckdb.connect(str(path))
    for table in tables:
        connection.execute(f"CREATE TABLE {table} (x INTEGER)")
    connection.close()
    return path


def test_a_complete_mirror_passes(tmp_path):
    path = _mirror(tmp_path / "full.duckdb", REQUIRED_TABLES)
    connection = DuckDbConnection(path)

    verify_mirror(connection)      # must not raise

    # missing_tables takes a raw connection -- the build scripts hold one of those.
    # Reaching through DuckDbConnection._connection would undo the point of routing
    # verification through the port.
    assert missing_tables(duckdb.connect(str(path), read_only=True)) == []
    connection.close()


def test_a_mirror_with_duckdb_tables_but_no_lance_directories_is_rejected(tmp_path):
    """jattr search lives in LanceDB now -- a mirror could have every DuckDB table
    (attribute_keys_index/attribute_values_index's own staging tables included) and
    still be missing the .lance directories nothing actually queries them through
    anymore. Only checked when db_path is given, same precedent as mirror_config."""
    path = _mirror(tmp_path / "no_lance.duckdb", REQUIRED_TABLES)
    connection = DuckDbConnection(path)

    with pytest.raises(IncompleteMirror) as raised:
        verify_mirror(connection, path)

    message = str(raised.value)
    for name in REQUIRED_LANCE_TABLES:
        assert f"{name}.lance" in message
    connection.close()


def test_the_partial_mirror_step3_leaves_behind_is_rejected(tmp_path):
    """Exactly the seven tables step3_assemble_mirror.py creates -- the shape that shipped."""
    built_by_step3 = {"sra_metadata", "sra_taxonomy", "stat_coverage",
                             "metalog_metadata", "metalog_metaphlan4",
                             "metalog_motus3", "metalog_spire_motus"}
    connection = DuckDbConnection(_mirror(tmp_path / "partial.duckdb", built_by_step3))

    with pytest.raises(IncompleteMirror) as raised:
        verify_mirror(connection, tmp_path / "partial.duckdb")

    message = str(raised.value)
    for table in ("schema_catalog", "attribute_keys_index",
                  "attribute_values_index", "column_value_embeddings"):
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


def test_a_rejected_mirror_is_not_cached_behind_the_global(tmp_path, monkeypatch):
    """`runtime.database()` memoises into a module global. Assigning that global before
    verifying would mean the first call raises, but the SECOND sails past the `is None`
    guard and returns the very connection the first call rejected -- unvalidated, with
    its DuckDB handle still open. So verification happens on a local, and only a mirror
    that passes is ever published."""
    import askslm
    from askslm import runtime

    closed = []

    class _Partial:
        """A Database that reports the seven tables step3 leaves behind."""

        def __init__(self, db_path, gpu=False):
            self.db_path = db_path

        def query(self, sql, params=None):
            return pd.DataFrame({"name": ["sra_metadata", "sra_taxonomy", "stat_coverage",
                                          "metalog_metadata", "metalog_metaphlan4",
                                          "metalog_motus3", "metalog_spire_motus"]})

        def close(self):
            closed.append(self)

    monkeypatch.setattr("askslm.runtime.DuckDbConnection", _Partial)
    db_path = tmp_path / "partial.duckdb"
    db_path.touch()
    askslm.config(db=db_path)

    for _ in range(2):
        with pytest.raises(IncompleteMirror):
            runtime.database()

    assert runtime._database is None       # never published
    assert len(closed) == 2                # and never leaked
