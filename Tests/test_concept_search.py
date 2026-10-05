"""Embedding-based retrieval for NATIVE low-cardinality column values whose wording
shares no characters with the question's: "IBD" finding "Crohn's disease" and
"ulcerative colitis" as subject_disease_status values, with no shared substring."""
import pandas as pd

from cohortquery.concept_search import ConceptIndex, render_values


class _FakeEmbedder:
    """Returns a fixed vector per input text, so nearest-neighbor distance is
    deterministic in tests -- no real Gemini call, no real semantics. Terms with
    no assigned vector get a default so extra terms in a question (e.g. "fecal",
    "metagenomic") don't crash the fake -- only the terms a test cares about need
    an explicit entry."""

    _DEFAULT = [0.0, 0.0]

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors.get(text, self._DEFAULT) for text in texts]


class _FakeValueEmbeddingDatabase:
    """Stands in for the Database port over column_value_embeddings.
    `rows` is (table_name, column_name, value, vector)."""

    def __init__(self, rows):
        self._rows = rows

    def query(self, sql, params=None):
        query_vector = params[0]
        limit = params[1]
        scored = sorted(self._rows, key=_distance_to(query_vector))
        top = scored[:limit]
        return pd.DataFrame(
            [(t, c, v) for t, c, v, _ in top],
            columns=["table_name", "column_name", "value"])


def _distance(a, b):
    """Squared Euclidean distance -- good enough to order fixed 2D test vectors;
    the real query uses DuckDB's array_cosine_distance, exercised separately in
    the fixture-backed integration test."""
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _distance_to(query_vector):
    """Returns a sort key function bound to query_vector, so `sorted(rows,
    key=...)` can rank each row by its distance to the query without a lambda."""
    def row_distance(row):
        return _distance(row[3], query_vector)
    return row_distance


IBD_VECTOR = [1.0, 0.0]
UNRELATED_VECTOR = [0.0, 1.0]


def test_matching_values_finds_disease_subtypes_for_an_umbrella_term():
    """The metalog case: subject_disease_status has "Crohn's disease" and
    "ulcerative colitis" but no "IBD" literal. Embedding search on the VALUE finds
    both from the umbrella term in the question."""
    values_db = _FakeValueEmbeddingDatabase([
        ("metalog_metadata", "subject_disease_status", "Crohn's disease", IBD_VECTOR),
        ("metalog_metadata", "subject_disease_status", "ulcerative colitis", IBD_VECTOR),
        ("metalog_metadata", "geographic_location", "Israel", UNRELATED_VECTOR),
    ])
    embedder = _FakeEmbedder({"IBD": IBD_VECTOR})
    index = ConceptIndex(values_db, embedder=embedder)

    found = index.matching_values("IBD cohort")

    assert found["metalog_metadata.subject_disease_status"] == [
        "Crohn's disease", "ulcerative colitis"]
    assert "metalog_metadata.geographic_location" not in found


def test_no_embedder_degrades_to_no_candidates():
    """A CannedLlmBackend (or a failed local-embedder call) returns [] from embed() --
    this must not raise, just contribute nothing."""
    class _EmptyEmbedder:
        def embed(self, texts):
            return []

    index = ConceptIndex(_FakeValueEmbeddingDatabase([]), embedder=_EmptyEmbedder())

    assert index.matching_values("IBD") == {}


def test_a_different_question_re_embeds():
    """The cache must not return stale vectors for a new question. A second,
    different question string is not the cached question -- it must trigger
    its own embed() call rather than replaying the first question's result."""
    class _SpyEmbedder:
        def __init__(self, vectors: dict[str, list[float]]):
            self._vectors = vectors
            self.calls = 0

        def embed(self, texts: list[str]) -> list[list[float]]:
            self.calls += 1
            return [self._vectors.get(text, [0.0, 0.0]) for text in texts]

    embedder = _SpyEmbedder({"IBD": IBD_VECTOR, "calprotectin": UNRELATED_VECTOR})
    index = ConceptIndex(_FakeValueEmbeddingDatabase([]), embedder=embedder)

    index.matching_values("IBD")
    index.matching_values("calprotectin")

    assert embedder.calls == 2


def test_render_values_formats_the_prompt_block():
    block = render_values({"metalog_metadata.subject_disease_status":
                           ["Crohn's disease", "ulcerative colitis"]})

    assert "subject_disease_status" in block
    assert "Crohn's disease" in block
    assert "ulcerative colitis" in block


def test_render_values_is_empty_when_nothing_matched():
    assert render_values({}) == ""
