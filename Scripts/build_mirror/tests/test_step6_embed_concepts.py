"""Embeds low-cardinality schema_catalog values into column_value_embeddings.
Uses a fake embedder throughout -- this must never load the real local model or
touch the network in a test run."""
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "steps"))
from step6_embed_concepts import ConceptEmbeddingBuilder


class _FakeEmbedder:
    """Deterministic: every vector is [len(text), 0.0] -- enough to prove wiring
    (right number of rows, right dimensionality) without needing real semantics."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 0.0] for text in texts]


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "mini.duckdb"
    con = duckdb.connect(str(path))
    con.execute("""CREATE TABLE schema_catalog (
        table_name TEXT, column_name TEXT, data_type TEXT,
        distinct_count BIGINT, truncated BOOLEAN, values_json TEXT)""")
    con.executemany("INSERT INTO schema_catalog VALUES (?, ?, ?, ?, ?, ?)", [
        ("metalog_metadata", "subject_disease_status", "VARCHAR", 3, False,
         '["Crohn\'s disease", "ulcerative colitis", "healthy control"]'),
        ("sra_metadata", "sample_name", "VARCHAR", 30505772, True, '["GB_513_1"]'),
    ])
    con.close()
    return path


def test_only_complete_untruncated_vocabularies_are_embedded(db_path):
    """sample_name is truncated (near-unique, 30.5M distinct on the real mirror) --
    embedding it would be a per-row dump, not a vocabulary. Only the complete,
    low-cardinality columns qualify."""
    ConceptEmbeddingBuilder(db_path, embedder=_FakeEmbedder(), dim=2).build()

    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute(
        "SELECT DISTINCT table_name, column_name FROM column_value_embeddings").fetchall()
    con.close()

    assert rows == [("metalog_metadata", "subject_disease_status")]


def test_every_value_of_a_qualifying_column_gets_a_row(db_path):
    ConceptEmbeddingBuilder(db_path, embedder=_FakeEmbedder(), dim=2).build()

    con = duckdb.connect(str(db_path), read_only=True)
    values = con.execute(
        "SELECT value FROM column_value_embeddings ORDER BY value").fetchall()
    con.close()

    assert values == [("Crohn's disease",), ("healthy control",), ("ulcerative colitis",)]


def test_vectors_have_the_requested_dimensionality(db_path):
    ConceptEmbeddingBuilder(db_path, embedder=_FakeEmbedder(), dim=2).build()

    con = duckdb.connect(str(db_path), read_only=True)
    vector = con.execute(
        "SELECT vector FROM column_value_embeddings LIMIT 1").fetchone()[0]
    con.close()

    assert len(vector) == 2
