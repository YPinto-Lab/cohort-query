"""Proves the real SQL against a real DuckDB file -- the unit tests in
test_jattr_concepts.py fake the Database port; this one does not."""
from askslm.adapters import DuckDbConnection
from askslm.concept_search import EMBED_DIM
from askslm.jattr_concepts import JattrConceptIndex
from askslm.translation import JattrCriterion
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
    """The bug this feature exists to fix: "IBD" (3 chars) shares no substring
    with ibd_sam. Embedding search finds it by meaning, through the real
    attribute_keys_index table and a real HNSW query, not a fake."""
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    try:
        index = JattrConceptIndex(connection, embedder=_FixtureEmbedder())

        found = index.matching((JattrCriterion(concept="IBD"),))

        matched_on = {match.matched_on for match in found["IBD"]}
        assert "ibd_sam" in matched_on
    finally:
        connection.close()
