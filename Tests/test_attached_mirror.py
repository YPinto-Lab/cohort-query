"""The package re-attaches the SRA source recorded in the mirror.

The real mirror does not contain sra_taxonomy -- it contains a VIEW over a second
database file holding 13.6 billion rows. config(db=...) still takes one path, so the
connection has to find the second one itself. If this breaks, every STAT query fails
with "table not found" against the real mirror while passing against the fixture.
"""
import duckdb
import pytest

from askslm.adapters import DuckDbConnection, _gpu_wrapped


@pytest.fixture
def split_mirror(tmp_path):
    """A two-file mirror, shaped like the real one: metadata copied, taxonomy attached."""
    source = tmp_path / "sra.duckdb"
    connection = duckdb.connect(str(source))
    connection.execute("CREATE TABLE tax_raw (acc VARCHAR, tax_id INTEGER, self_count BIGINT)")
    connection.execute("INSERT INTO tax_raw VALUES ('SRR1', 562, 10), ('SRR2', 562, 20)")
    connection.close()

    mirror = tmp_path / "mirror.duckdb"
    connection = duckdb.connect(str(mirror))
    connection.execute(f"ATTACH '{source}' AS sra (READ_ONLY)")
    connection.execute("CREATE VIEW sra_taxonomy AS SELECT * FROM sra.tax_raw")
    connection.execute("CREATE TABLE mirror_config (key VARCHAR, value VARCHAR)")
    connection.execute("INSERT INTO mirror_config VALUES ('sra_db_path', ?)", [str(source)])
    connection.close()
    return mirror


def test_connection_attaches_the_recorded_source_and_the_view_resolves(split_mirror):
    connection = DuckDbConnection(split_mirror)

    rows = connection.query("SELECT acc, self_count FROM sra_taxonomy ORDER BY acc")

    assert list(rows["acc"]) == ["SRR1", "SRR2"]
    connection.close()


def test_a_single_file_fixture_without_mirror_config_still_opens(tmp_path):
    """The generated fixture is one self-contained file. It must not need an attach."""
    path = tmp_path / "plain.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("CREATE TABLE sra_taxonomy (acc VARCHAR)")
    connection.execute("INSERT INTO sra_taxonomy VALUES ('SRR9')")
    connection.close()

    connection = DuckDbConnection(path)

    assert list(connection.query("SELECT acc FROM sra_taxonomy")["acc"]) == ["SRR9"]
    connection.close()


def test_the_mirror_is_read_only(split_mirror):
    connection = DuckDbConnection(split_mirror)

    with pytest.raises(duckdb.Error):
        connection.query("CREATE TABLE injected (x INTEGER)")

    connection.close()


def test_gpu_mode_wraps_the_sql_in_gpu_processing():
    sql, params = _gpu_wrapped("SELECT 1", [], gpu=True)
    assert sql == "SELECT * FROM gpu_processing($$ SELECT 1 $$)"
    assert params == []


def test_cpu_mode_leaves_the_sql_and_params_unchanged():
    sql, params = _gpu_wrapped("SELECT 1", ["x"], gpu=False)
    assert sql == "SELECT 1"
    assert params == ["x"]


def test_gpu_mode_inlines_a_scalar_param_instead_of_binding_it():
    sql, params = _gpu_wrapped("SELECT * FROM t WHERE k = ?", ["v"], gpu=True)
    assert sql == "SELECT * FROM gpu_processing($$ SELECT * FROM t WHERE k = 'v' $$)"
    assert params == []


def test_gpu_mode_inlines_a_list_param_as_a_sql_array_literal():
    sql, params = _gpu_wrapped(
        "SELECT * FROM t WHERE acc IN (SELECT unnest(?::VARCHAR[]))",
        [["a", "b"]], gpu=True)
    assert "['a', 'b']" in sql
    assert params == []


def test_gpu_mode_escapes_single_quotes_in_an_inlined_param():
    sql, params = _gpu_wrapped("SELECT * FROM t WHERE k = ?", ["o'brien"], gpu=True)
    assert "o''brien" in sql


def test_gpu_mode_fails_fast_when_the_extension_is_missing(tmp_path):
    plain = tmp_path / "plain.duckdb"
    connection = duckdb.connect(str(plain))
    connection.execute("CREATE TABLE t (x INTEGER)")
    connection.close()

    with pytest.raises(duckdb.Error):
        DuckDbConnection(plain, gpu=True)
