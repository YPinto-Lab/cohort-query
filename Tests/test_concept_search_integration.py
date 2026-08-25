"""Proves the real SQL against a real DuckDB file -- the unit tests in
test_concept_search.py fake the Database port; this one does not."""
from askslm.adapters import DuckDbConnection
from askslm.concept_search import EMBED_DIM, ConceptIndex
from fixtures.mirror import build_fixture_mirror


class _FixtureEmbedder:
    """Same mapping as Tests/fixtures/mirror.py's _FixtureEmbedder -- duplicated here
    deliberately rather than imported, so this test does not reach into the ETL
    script's test-only helper. If the two drift, this test is what catches it."""

    _KNOWN_TERMS = frozenset({"IBD", "Crohn's disease", "ulcerative colitis", "ibd_sam"})

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for(text) for text in texts]

    def _vector_for(self, text: str) -> list[float]:
        vector = [0.0] * EMBED_DIM
        index = 0 if text in self._KNOWN_TERMS else 1 + (len(text) % (EMBED_DIM - 1))
        vector[index] = 1.0
        return vector


def test_a_short_acronym_finds_ibd_sam_through_real_duckdb_vss(tmp_path):
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    try:
        index = ConceptIndex(connection, connection, embedder=_FixtureEmbedder())

        found = index.matching_keys("IBD")

        assert "ibd_sam" in found
    finally:
        connection.close()


def test_ibd_finds_both_disease_subtypes_through_real_duckdb_vss(tmp_path):
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    try:
        index = ConceptIndex(connection, connection, embedder=_FixtureEmbedder())

        found = index.matching_values("IBD")

        values = found.get("metalog_metadata.subject_disease_status", [])
        assert "Crohn's disease" in values
        assert "ulcerative colitis" in values
    finally:
        connection.close()
