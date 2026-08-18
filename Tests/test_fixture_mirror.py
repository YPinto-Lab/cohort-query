"""The fixture mirror has the structure the build engine is specified against.

If these fail, every downstream test is asserting against the wrong world.
Expected values are hardcoded on purpose -- recomputing them from the fixture's
own constants would assert nothing.
"""
import pytest

from fixtures.mirror import build_fixture_mirror

import duckdb


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    path = build_fixture_mirror(tmp_path_factory.mktemp("mirror") / "fixture.duckdb")
    connection = duckdb.connect(str(path), read_only=True)
    yield connection
    connection.close()


def _one(con, sql):
    return con.execute(sql).fetchone()[0]


def test_cohort_partitions_into_shared_sra_only_and_metalog_only(con):
    shared = _one(con, """
        SELECT count(*) FROM (SELECT DISTINCT biosample FROM sra_metadata) s
        JOIN (SELECT DISTINCT biosample FROM metalog_metadata WHERE biosample IS NOT NULL) m
          USING (biosample)
    """)
    sra_only = _one(con, """
        SELECT count(*) FROM (SELECT DISTINCT biosample FROM sra_metadata) s
        WHERE biosample NOT IN (SELECT biosample FROM metalog_metadata WHERE biosample IS NOT NULL)
    """)
    metalog_only = _one(con, """
        SELECT count(*) FROM (SELECT DISTINCT biosample FROM metalog_metadata WHERE biosample IS NOT NULL) m
        WHERE biosample NOT IN (SELECT biosample FROM sra_metadata)
    """)

    assert (shared, sra_only, metalog_only) == (8, 6, 4)


def test_metalog_keeps_an_orphan_tail_with_no_biosample(con):
    orphans = _one(con, "SELECT count(*) FROM metalog_metadata WHERE biosample IS NULL")

    assert orphans == 2


def test_the_two_motus_sources_overlap_and_each_add_their_own_samples(con):
    motus3 = _one(con, "SELECT count(DISTINCT sample_alias) FROM metalog_motus3")
    spire = _one(con, "SELECT count(DISTINCT sample_alias) FROM metalog_spire_motus")
    overlap = _one(con, """
        SELECT count(*) FROM (SELECT DISTINCT sample_alias FROM metalog_motus3)
        SEMI JOIN (SELECT DISTINCT sample_alias FROM metalog_spire_motus) USING (sample_alias)
    """)
    spire_unique = _one(con, """
        SELECT count(*) FROM (SELECT DISTINCT sample_alias FROM metalog_spire_motus)
        ANTI JOIN (SELECT DISTINCT sample_alias FROM metalog_motus3) USING (sample_alias)
    """)

    assert (motus3, spire, overlap, spire_unique) == (8, 7, 3, 4)


def test_overlapping_samples_carry_different_values_so_head_wins_is_observable(con):
    values = con.execute("""
        SELECT m.rel_abund, s.rel_abund
        FROM metalog_motus3 m JOIN metalog_spire_motus s
          ON m.sample_alias = s.sample_alias AND m.species = s.species
        WHERE m.sample_alias = 'MG_SAMN00004'
    """).fetchall()

    assert values, "the overlap must be non-empty or head-wins cannot be tested"
    assert all(from_motus3 != from_spire for from_motus3, from_spire in values)


def test_spire_contributes_a_species_motus3_has_never_seen(con):
    only_in_spire = _one(con, """
        SELECT count(*) FROM (SELECT DISTINCT species FROM metalog_spire_motus)
        ANTI JOIN (SELECT DISTINCT species FROM metalog_motus3) USING (species)
    """)

    assert only_in_spire == 1


def test_one_biosample_has_two_runs_that_become_two_columns(con):
    """B.3: STAT columns are RUNS. Two runs of one biosample stay two columns -- never
    summed, never selected down to one. Both must be distinguishable and both must
    resolve to the same biosample."""
    runs = [row[0] for row in con.execute("""
        SELECT DISTINCT t.acc FROM sra_taxonomy t
        JOIN sra_metadata m ON m.biosample = 'SAMN00001'
        WHERE t.acc LIKE 'SRR00001%' ORDER BY 1
    """).fetchall()]
    profiles = con.execute("""
        SELECT acc, sum(self_count) FROM sra_taxonomy
        WHERE acc LIKE 'SRR00001%' GROUP BY acc ORDER BY acc
    """).fetchall()

    assert runs == ["SRR00001A", "SRR00001B"]
    assert profiles[0][1] != profiles[1][1], "distinct profiles, so collapsing them would lose data"


def test_sra_taxonomy_is_keyed_by_run_only_and_stat_coverage_stands_in_for_it(con):
    """This assertion has now flipped twice, so the reasoning is worth recording.

    First it asserted `biosample` was ABSENT (a defect: STAT unreachable by the canonical
    key). Then PR #18 stamped it and this asserted it PRESENT. The real table then turned
    out to be 13.6 BILLION rows, where that stamping means rewriting everything -- and
    B.3's decision that a STAT column is a RUN makes it unnecessary: biosamples resolve
    to runs via sra_metadata, and the huge table is only ever filtered by its own `acc`.

    So `biosample` is absent again, on purpose this time, and `stat_coverage` carries the
    one thing the stamping was really wanted for: cheap preview counts.
    """
    columns = [row[0] for row in con.execute("DESCRIBE sra_taxonomy").fetchall()]
    covered = _one(con, "SELECT count(*) FROM stat_coverage")
    distinct_runs = _one(con, "SELECT count(DISTINCT acc) FROM sra_taxonomy")

    assert "acc" in columns
    assert "biosample" not in columns
    assert covered == distinct_runs


def test_profile_lineage_column_differs_per_source(con):
    metaphlan = [row[0] for row in con.execute("DESCRIBE metalog_metaphlan4").fetchall()]
    motus = [row[0] for row in con.execute("DESCRIBE metalog_motus3").fetchall()]

    assert "clade_name" in metaphlan and "species" not in metaphlan
    assert "species" in motus and "clade_name" not in motus


def test_metadata_has_low_cardinality_columns_for_the_value_vocabularies(con):
    diseases = _one(con, "SELECT count(DISTINCT subject_disease_status) FROM metalog_metadata")
    countries = _one(con, "SELECT count(DISTINCT geographic_location) FROM metalog_metadata")

    assert diseases == 3
    assert countries == 4
