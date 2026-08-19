"""Phenotype hides in jattr. 35,768 distinct keys in a 200k-row sample, and the
interesting ones are RARE -- calprotectin_sam is in 0.006% of runs. Indexing lets a
researcher name one and have it found."""
import duckdb
import pandas as pd
import pytest

from askslm.attributes import GENERIC_KEYS, AttributeIndex, render
from fixtures.mirror import build_fixture_mirror


class _FakeDatabase:
    """Stands in for a Database port over `attribute_keys`, matching the same
    substring semantics as the real `LIKE '%term%'` query."""

    def __init__(self, rows):
        self._rows = rows          # list of (key, occurrences, samples_json)

    def query(self, sql, params=None):
        """Two shapes: the generic-term count, and the per-term key lookup."""
        term = params[0].strip("%")
        matched = [row for row in self._rows if term in row[0].lower()]
        if "count(*)" in sql:
            return pd.DataFrame({"n": [len(matched)]})
        matched.sort(key=_occurrences, reverse=True)
        return pd.DataFrame(matched[:params[1]],
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


def test_a_key_with_no_sampled_value_renders_without_crashing():
    """DuckDB NULL arrives from pandas as float NaN, and NaN is TRUTHY -- so a plain
    `if samples` check sent NaN into json.loads. 58,196 of the real mirror's 94,450 keys
    have no sampled value, so this fired on the very first real query."""
    block = render({"lonely_key": (7, float("nan"))})

    assert "lonely_key" in block
    assert "e.g." not in block


def test_a_broad_term_cannot_crowd_out_a_precise_one():
    """The bug this budget exists to prevent. "fecal" matches many low-value keys; with
    one global ranking they filled every slot and evicted fecalcalprotectin_run, which is
    the key the researcher meant. Each term gets its own slots instead."""
    noise = [(f"fecal_noise_{n}_sam", 5000 + n, None) for n in range(20)]
    index = AttributeIndex(_FakeDatabase(noise + [("fecalcalprotectin_run", 134, None)]))

    found = index.matching("fecal metagenomic with calprotectin")

    assert "fecalcalprotectin_run" in found


class _StubExpander:
    def __init__(self, terms):
        self._terms = terms

    def expand(self, question):
        return self._terms


def test_model_synonyms_reach_keys_the_question_wording_cannot():
    """The point of expansion. A researcher writes "calprotectin"; the submitting lab
    wrote host_calpro_sam. Measured on the real mirror: `calpro` reaches 25 keys across
    8,539 runs that the literal word never touches."""
    index = AttributeIndex(_FakeDatabase([("host_calpro_sam", 117, None)]),
                           expander=_StubExpander(["calpro"]))

    assert "host_calpro_sam" in index.matching("fecal samples with calprotectin")


def test_a_generic_term_is_dropped_by_measurement_not_by_trust():
    """`dna` matches 698 keys across 1,067,427 runs on the real mirror and would fill the
    whole budget with noise. The instruction tells the model not to emit generic terms;
    this drops them anyway when it does."""
    rows = [(f"dna_thing_{n}_sam", 100, None) for n in range(GENERIC_KEYS + 5)]
    index = AttributeIndex(_FakeDatabase(rows), expander=_StubExpander(["dna"]))

    assert index.matching("stool samples") == {}
