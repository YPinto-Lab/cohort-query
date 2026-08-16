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


def test_one_biosample_has_two_runs_so_stat_counts_must_be_summed(con):
    runs = _one(con, """
        SELECT count(DISTINCT acc) FROM sra_taxonomy WHERE acc LIKE 'SRR00001%'
    """)
    summed = _one(con, """
        SELECT sum(self_count) FROM sra_taxonomy WHERE acc LIKE 'SRR00001%' AND tax_id = 562
    """)
    single_run = _one(con, """
        SELECT self_count FROM sra_taxonomy WHERE acc = 'SRR00001A' AND tax_id = 562
    """)

    assert runs == 2
    assert summed > single_run


def test_sra_taxonomy_is_keyed_by_run_not_biosample(con):
    """Locks in the defect found in HLD B.3 -- STAT cannot be read by the canonical key."""
    columns = [row[0] for row in con.execute("DESCRIBE sra_taxonomy").fetchall()]

    assert "acc" in columns
    assert "biosample" not in columns


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
