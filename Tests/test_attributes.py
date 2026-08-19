"""Phenotype hides in jattr. 35,768 distinct keys in a 200k-row sample, and the
interesting ones are RARE -- calprotectin_sam is in 0.006% of runs. Indexing lets a
researcher name one and have it found."""
import duckdb
import pandas as pd
import pytest

from askslm.attributes import AttributeIndex
from fixtures.mirror import build_fixture_mirror


class _FakeDatabase:
    """Stands in for a Database port over `attribute_keys`, matching the same
    substring semantics as the real `LIKE '%term%'` query."""

    def __init__(self, rows):
        self._rows = rows          # list of (key, occurrences, samples_json)

    def query(self, sql, params=None):
        patterns, limit = params
        terms = [pattern.strip("%") for pattern in patterns]
        matched = [row for row in self._rows
                  if any(term in row[0].lower() for term in terms)]
        matched.sort(key=_occurrences, reverse=True)
        return pd.DataFrame(matched[:limit],
                            columns=["key", "occurrences", "samples_json"])


def _occurrences(row):
    return row[1]


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    path = build_fixture_mirror(tmp_path_factory.mktemp("attrs") / "fixture.duckdb")
    connection = duckdb.connect(str(path), read_only=True)
    yield connection
    connection.close()


def test_every_jattr_key_is_indexed_with_its_occurrence_count(con):
    rows = con.execute(
        "SELECT key, occurrences FROM attribute_keys ORDER BY key").fetchall()

    assert ("host_age", 15) in rows          # the fixture's one jattr key, on every run


def test_the_index_carries_sample_values_so_the_model_sees_the_format(con):
    """`calprotectin_sam` holds "435.0" -- a NUMBER STORED AS A STRING. Without a sample
    the model cannot know it needs TRY_CAST."""
    samples = con.execute(
        "SELECT samples_json FROM attribute_keys WHERE key = 'host_age'").fetchone()[0]

    assert samples is not None and samples != "[]"


def test_a_named_phenotype_is_retrieved_from_the_index():
    """The whole point: "with calprotectin" must find calprotectin_sam."""
    index = AttributeIndex(_FakeDatabase([
        ("calprotectin_sam", 2342, '["435.0","12.8"]'),
    ]))

    found = index.matching("IBD fecal metagenomic with calprotectin")

    assert "calprotectin_sam" in found


def test_short_and_common_words_do_not_match_everything():
    """Without a floor, "with" and "a" match half the index and the prompt fills with
    noise -- the exact failure this feature exists to fix."""
    index = AttributeIndex(_FakeDatabase([("with_something", 10, None)]))

    assert index.matching("samples with a disease") == {}
