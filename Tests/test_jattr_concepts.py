"""JattrConceptIndex: a concept -> biosamples, searching BOTH attribute_keys_index
(presence) and attribute_values_index (content), always -- recall-first, no
per-criterion "which table" judgment call. See jattr_concepts.py."""
import pandas as pd

from cohortquery.accession import Accession
from cohortquery.jattr_concepts import JattrConceptIndex, LanceAttributeIndexes
from cohortquery.translation import JattrCriterion


class _FakeLanceTable:
    """Stands in for a Lance table handle (LanceAttributeIndexes.keys_table /
    values_table). `rows` is (text, biosample_list, vector); `column` is
    "key" or "value" -- the table's own text column name, matching the real
    Lance schema so JattrConceptIndex's itertuples() row.key / row.value
    access works unchanged against the fake."""

    def __init__(self, rows, column):
        self._rows = rows
        self._column = column

    def search(self, query_vector):
        return _FakeSearch(self._rows, query_vector, self._column)


class _FakeSearch:
    """Stands in for the Lance query builder .search(vector).limit(n) returns,
    ending in .to_pandas() -- exactly the chain JattrConceptIndex calls."""

    def __init__(self, rows, query_vector, column):
        self._rows = rows
        self._query_vector = query_vector
        self._column = column
        self._limit = len(rows)

    def limit(self, n):
        self._limit = n
        return self

    def to_pandas(self):
        scored = sorted(self._rows, key=_distance_to(self._query_vector))
        top = scored[:self._limit]
        return pd.DataFrame([(name, biosamples) for name, biosamples, _ in top],
                            columns=[self._column, "biosample"])


def _distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _distance_to(query_vector):
    def row_distance(row):
        return _distance(row[2], query_vector)
    return row_distance


def _fake_indexes(key_rows=(), value_rows=()):
    return LanceAttributeIndexes(
        keys_table=_FakeLanceTable(key_rows, "key"),
        values_table=_FakeLanceTable(value_rows, "value"))


class _FakeEmbedder:
    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors[text] for text in texts]


CALPROTECTIN_VECTOR = [1.0, 0.0]
IBD_VECTOR = [0.0, 1.0]
UNRELATED_VECTOR = [1.0, 1.0]


def test_a_presence_concept_matches_through_the_keys_table():
    """"calprotectin measurement" naturally lands on a KEY, via attribute_keys_index --
    no upfront "presence vs content" declaration needed."""
    index = JattrConceptIndex(
        _fake_indexes(
            key_rows=[("calprotectin_sam", ["SAMN001", "SAMN002"], CALPROTECTIN_VECTOR),
                     ("unrelated_key", ["SAMN099"], UNRELATED_VECTOR)]),
        embedder=_FakeEmbedder({"calprotectin measurement": CALPROTECTIN_VECTOR}))

    found = index.matching((JattrCriterion(concept="calprotectin measurement"),))

    matches = found["calprotectin measurement"]
    assert any(match.matched_on == "calprotectin_sam" for match in matches)
    hit = next(match for match in matches if match.matched_on == "calprotectin_sam")
    assert hit.biosamples == {Accession("SAMN001"), Accession("SAMN002")}


def test_a_content_concept_matches_through_the_values_table():
    """"IBD" naturally lands on a VALUE, via attribute_values_index."""
    index = JattrConceptIndex(
        _fake_indexes(
            value_rows=[("IBD", ["SAMN003"], IBD_VECTOR),
                       ("unrelated value", ["SAMN098"], UNRELATED_VECTOR)]),
        embedder=_FakeEmbedder({"IBD diagnosis": IBD_VECTOR}))

    found = index.matching((JattrCriterion(concept="IBD diagnosis"),))

    matches = found["IBD diagnosis"]
    assert any(match.matched_on == "IBD" for match in matches)


def test_both_tables_are_always_searched_and_unioned():
    """A single concept can legitimately match BOTH a key and a value -- both
    searches always run, nothing is skipped based on a guess about which kind
    of match the concept "should" be."""
    index = JattrConceptIndex(
        _fake_indexes(
            key_rows=[("ibd_sam", ["SAMN001"], IBD_VECTOR)],
            value_rows=[("IBD", ["SAMN002"], IBD_VECTOR)]),
        embedder=_FakeEmbedder({"IBD": IBD_VECTOR}))

    found = index.matching((JattrCriterion(concept="IBD"),))

    matched_on = {match.matched_on for match in found["IBD"]}
    assert matched_on == {"ibd_sam", "IBD"}


def test_multiple_criteria_embed_in_one_call():
    """One embed() call for every criterion's concept at once -- the "one live call
    per ask()" design commits to, regardless of how many jattr criteria a
    question has."""
    class _SpyEmbedder:
        def __init__(self, vectors):
            self._vectors = vectors
            self.calls = 0

        def embed(self, texts):
            self.calls += 1
            return [self._vectors[text] for text in texts]

    embedder = _SpyEmbedder({"IBD": IBD_VECTOR, "calprotectin measurement": CALPROTECTIN_VECTOR})
    index = JattrConceptIndex(_fake_indexes(), embedder=embedder)

    index.matching((JattrCriterion(concept="IBD"),
                    JattrCriterion(concept="calprotectin measurement")))

    assert embedder.calls == 1


def test_no_criteria_skips_the_embed_call_entirely():
    class _EmbedderThatMustNotBeCalled:
        def embed(self, texts):
            raise AssertionError("embed() called with no criteria")

    index = JattrConceptIndex(_fake_indexes(), embedder=_EmbedderThatMustNotBeCalled())

    assert index.matching(()) == {}
