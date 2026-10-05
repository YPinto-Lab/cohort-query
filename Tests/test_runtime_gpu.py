"""config(gpu=...) has to actually reach DuckDbConnection's constructor -- an
interactive session's own connection must never be gpu mode; only a worker's
explicit config() call is."""
import pandas as pd

import cohortquery
from cohortquery import runtime
from cohortquery.adapters import REQUIRED_TABLES


class _RecordingConnection:
    """A Database double. It reports a complete mirror because these tests are about
    gpu passthrough, not about completeness -- but it must answer `query` at all, since
    runtime.database() verifies the mirror through the port before handing it back."""

    def __init__(self, db_path, gpu=False):
        self.db_path = db_path
        self.gpu = gpu

    def query(self, sql, params=None):
        return pd.DataFrame({"name": sorted(REQUIRED_TABLES)})


def test_database_passes_gpu_through_to_the_connection(tmp_path, monkeypatch):
    monkeypatch.setattr("cohortquery.runtime.DuckDbConnection", _RecordingConnection)
    db_path = tmp_path / "fixture.duckdb"
    db_path.touch()

    cohortquery.config(db=db_path, gpu=True)
    connection = runtime.database()

    assert connection.gpu is True


def test_gpu_defaults_to_false(tmp_path, monkeypatch):
    monkeypatch.setattr("cohortquery.runtime.DuckDbConnection", _RecordingConnection)
    db_path = tmp_path / "fixture.duckdb"
    db_path.touch()

    cohortquery.config(db=db_path)
    connection = runtime.database()

    assert connection.gpu is False
