"""Proves real vector search against real Lance tables -- the unit tests in
test_jattr_concepts.py fake the two Lance table handles; this one does not."""
from cohortquery.concept_search import EMBED_DIM
from cohortquery.jattr_concepts import JattrConceptIndex
from cohortquery.translation import JattrCriterion
from fixtures.mirror import build_fixture_mirror, open_fixture_attribute_indexes


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


def test_a_short_acronym_finds_ibd_sam_through_real_lance_search(tmp_path):
    """The bug this feature exists to fix: "IBD" (3 chars) shares no substring
    with ibd_sam. Embedding search finds it by meaning, through the real
    attribute_keys_index Lance table and a real (brute-force, unindexed at
    this scale) vector search, not a fake."""
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    indexes = open_fixture_attribute_indexes(path)
    index = JattrConceptIndex(indexes, embedder=_FixtureEmbedder())

    found = index.matching((JattrCriterion(concept="IBD"),))

    matched_on = {match.matched_on for match in found["IBD"]}
    assert "ibd_sam" in matched_on
