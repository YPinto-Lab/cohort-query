"""Embeds attribute_keys and low-cardinality schema_catalog values into two new
tables. Uses a fake embedder throughout -- this must never call the real Gemini API
in a test run."""
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "steps"))
import step6_embed_concepts
from step6_embed_concepts import ConceptEmbeddingBuilder


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """Retry backoff and batch pacing are real seconds in production, not in tests --
    a real 5s+10s+20s+40s+80s retry ladder would make test_short_batch... alone take
    over two minutes."""
    monkeypatch.setattr(step6_embed_concepts.time, "sleep", _no_sleep)


def _no_sleep(seconds: float) -> None:
    return None


class _FakeEmbedder:
    """Deterministic: every vector is [len(text), 0.0] -- enough to prove wiring
    (right number of rows, right dimensionality) without needing real semantics."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 0.0] for text in texts]


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "mini.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE attribute_keys (key TEXT, occurrences BIGINT, samples_json TEXT)")
    con.executemany("INSERT INTO attribute_keys VALUES (?, ?, ?)", [
        ("ibd_sam", 44976, None),
        ("calprotectin_sam", 2342, '["435.0"]'),
    ])
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


def test_every_key_gets_one_embedding_row(db_path):
    ConceptEmbeddingBuilder(db_path, embedder=_FakeEmbedder(), dim=2).build()

    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute("SELECT key FROM attribute_key_embeddings ORDER BY key").fetchall()
    con.close()

    assert rows == [("calprotectin_sam",), ("ibd_sam",)]


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
        "SELECT vector FROM attribute_key_embeddings WHERE key = 'ibd_sam'").fetchone()[0]
    con.close()

    assert len(vector) == 2


class _ShortBatchEmbedder:
    """Simulates a transient embed-call failure: silently returns one fewer vector
    than requested, mimicking GeminiBackend.embed()'s degrade-to-[]-on-error contract.
    Proves the builder refuses to zip() a short batch against the wrong keys."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 0.0] for text in texts[:-1]]


def test_short_batch_from_embedder_raises_instead_of_corrupting_index(db_path):
    with pytest.raises(RuntimeError):
        ConceptEmbeddingBuilder(db_path, embedder=_ShortBatchEmbedder(), dim=2).build()

    # The table exists (created before the failing embed call) but must be empty --
    # no misaligned (key, vector) rows were ever inserted into it.
    con = duckdb.connect(str(db_path), read_only=True)
    count = con.execute("SELECT count(*) FROM attribute_key_embeddings").fetchone()[0]
    con.close()

    assert count == 0


class _CountingEmbedder:
    """Counts how many embed() calls actually happened -- a cost cap that aborted
    correctly must call embed() zero times, since the check runs BEFORE the call."""

    def __init__(self):
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(len(text)), 0.0] for text in texts]


def test_a_zero_cost_cap_aborts_before_spending_anything(db_path):
    """max_cost_usd=0 must reject even the smallest real batch -- proves the check
    runs BEFORE the embed() call it would pay for, not after."""
    embedder = _CountingEmbedder()

    with pytest.raises(RuntimeError, match="aborting before spending"):
        ConceptEmbeddingBuilder(db_path, embedder=embedder, dim=2, max_cost_usd=0.0).build()

    assert embedder.calls == 0
