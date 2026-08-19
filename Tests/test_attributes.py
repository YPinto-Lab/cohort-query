"""Phenotype hides in jattr. 35,768 distinct keys in a 200k-row sample, and the
interesting ones are RARE -- calprotectin_sam is in 0.006% of runs. Indexing lets a
researcher name one and have it found."""
import duckdb
import pytest

from fixtures.mirror import build_fixture_mirror


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
