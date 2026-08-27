"""DuckDbConnection must load vss so array_cosine_distance and HNSW indexes work --
without it, any query touching the embedding tables raises a Catalog Error."""
from pathlib import Path

from askslm.adapters import DuckDbConnection
from fixtures.mirror import build_fixture_mirror


def test_vss_functions_are_usable_after_connecting(tmp_path: Path) -> None:
    """Verify that VSS functions like array_cosine_distance are available immediately
    after connecting, without requiring manual LOAD vss."""
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)

    result = connection.query(
        "SELECT array_cosine_distance([1.0,0.0]::FLOAT[2], [1.0,0.0]::FLOAT[2]) AS d")

    assert result["d"][0] == 0.0
    connection.close()
