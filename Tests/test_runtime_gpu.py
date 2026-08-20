"""config(gpu=...) has to actually reach DuckDbConnection's constructor -- an
interactive session's own connection must never be gpu mode; only a worker's
explicit config() call is."""
import askslm
from askslm import runtime


class _RecordingConnection:
    def __init__(self, db_path, gpu=False):
        self.db_path = db_path
        self.gpu = gpu


def test_database_passes_gpu_through_to_the_connection(tmp_path, monkeypatch):
    monkeypatch.setattr("askslm.runtime.DuckDbConnection", _RecordingConnection)
    db_path = tmp_path / "fixture.duckdb"
    db_path.touch()

    askslm.config(db=db_path, gpu=True)
    connection = runtime.database()

    assert connection.gpu is True


def test_gpu_defaults_to_false(tmp_path, monkeypatch):
    monkeypatch.setattr("askslm.runtime.DuckDbConnection", _RecordingConnection)
    db_path = tmp_path / "fixture.duckdb"
    db_path.touch()

    askslm.config(db=db_path)
    connection = runtime.database()

    assert connection.gpu is False
