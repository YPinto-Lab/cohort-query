"""Resumable checkpoints for a cohort build: discovery (~10 min) and the profile scan
(~1 hour) are the expensive stages. Found on a real cluster incident (job 23680753,
OOM-killed after 66 minutes with zero output) -- these persist each stage so a crash
after either one doesn't force a full replay.
"""
import pandas as pd

from cohortquery import checkpoint
from cohortquery.build import BiomFactory, CohortBuilder, Materialization
from cohortquery.cohort import Accession, Cohort
from cohortquery.metadata import ReconciledMetadata
from cohortquery.profiles import ProfileMatrix
from cohortquery.sources import Source
from cohortquery.translation import SourceQuery


def _cohort() -> Cohort:
    return Cohort({
        Source.SRA_METADATA: frozenset(Accession(a) for a in ["SAMN1", "SAMN2", "SAMN3"]),
        Source.METALOG_METADATA: frozenset(Accession(a) for a in ["SAMN2", "SAMN3", "SAMN4"]),
    })


def _matrix() -> ProfileMatrix:
    counts = pd.DataFrame({"SAMN1": [3, 0], "SAMN2": [0, 7]},
                          index=pd.Index(["tax1", "tax2"], name="feature"))
    lineage = pd.DataFrame({"name": ["Bacteroides", "Firmicutes"], "rank": ["genus", None]},
                           index=pd.Index(["tax1", "tax2"], name="feature"))
    return ProfileMatrix(counts, lineage,
                         {"SAMN1": Accession("SAMN1"), "SAMN2": Accession("SAMN2")})


def test_cohort_key_changes_with_sql():
    a = (SourceQuery(Source.SRA_METADATA, "SELECT 1"),)
    b = (SourceQuery(Source.SRA_METADATA, "SELECT 2"),)

    assert checkpoint.cohort_key(a) == checkpoint.cohort_key(a)
    assert checkpoint.cohort_key(a) != checkpoint.cohort_key(b)


def test_matrix_key_changes_with_profile_sources():
    key = checkpoint.cohort_key((SourceQuery(Source.SRA_METADATA, "SELECT 1"),))

    assert checkpoint.matrix_key(key, (Source.SRA_TAXONOMY,)) != \
        checkpoint.matrix_key(key, (Source.METALOG_MOTUS3,))


def test_cohort_round_trips_and_rejects_a_stale_key(tmp_path):
    cohort = _cohort()
    checkpoint.save_cohort(tmp_path, cohort, "k1")

    assert checkpoint.load_cohort(tmp_path, "k1").by_source == cohort.by_source
    assert checkpoint.load_cohort(tmp_path, "other-key") is None


def test_matrix_round_trip_preserves_values_dtype_and_index_name(tmp_path):
    matrix = _matrix()
    checkpoint.save_matrix(tmp_path, matrix, "k1")

    loaded = checkpoint.load_matrix(tmp_path, "k1")

    assert loaded.column_biosample == matrix.column_biosample
    pd.testing.assert_frame_equal(loaded.counts.sort_index(axis=1),
                                  matrix.counts.sort_index(axis=1))
    assert loaded.counts.values.dtype == matrix.counts.values.dtype
    assert checkpoint.load_matrix(tmp_path, "other-key") is None


def test_biom_output_is_identical_after_a_matrix_round_trip(tmp_path):
    matrix = _matrix()
    metadata = ReconciledMetadata(pd.DataFrame(
        {"disease": ["IBD", "healthy"]}, index=["SAMN1", "SAMN2"]))
    checkpoint.save_matrix(tmp_path, matrix, "k1")
    loaded = checkpoint.load_matrix(tmp_path, "k1")

    direct = BiomFactory().build(matrix, metadata)
    via_checkpoint = BiomFactory().build(loaded, metadata)

    assert direct.ids("observation").tolist() == via_checkpoint.ids("observation").tolist()
    assert direct.ids("sample").tolist() == via_checkpoint.ids("sample").tolist()
    assert (direct.matrix_data != via_checkpoint.matrix_data).nnz == 0


class _FakeDiscovery:
    def __init__(self, cohort: Cohort):
        self.calls = 0
        self._cohort = cohort

    def discover(self, queries):
        self.calls += 1
        return self._cohort


class _FakeProfiles:
    def __init__(self, matrix: ProfileMatrix):
        self.calls = 0
        self._matrix = matrix

    def read(self, profile_sources, accessions):
        self.calls += 1
        return self._matrix


class _FakeMetadata:
    def reconciled(self, cohort, winning_source):
        return ReconciledMetadata(pd.DataFrame(
            {"disease": ["IBD", "healthy"]}, index=["SAMN1", "SAMN2"]))


def test_build_reuses_a_valid_checkpoint_and_cleans_up_on_success(tmp_path):
    cohort, matrix = _cohort(), _matrix()
    discovery, profiles = _FakeDiscovery(cohort), _FakeProfiles(matrix)
    builder = CohortBuilder(discovery, profiles, _FakeMetadata(), BiomFactory())
    queries = (SourceQuery(Source.SRA_METADATA, "SELECT 1"),)
    request = Materialization(profile_sources=(Source.SRA_TAXONOMY,),
                              metadata_winning_source=Source.METALOG_METADATA)
    key = checkpoint.cohort_key(queries)
    checkpoint.save_cohort(tmp_path, cohort, key)
    checkpoint.save_matrix(tmp_path, matrix, checkpoint.matrix_key(key, request.profile_sources))

    builder.build(queries, request, out=None, plan_dir=tmp_path)

    assert discovery.calls == 0 and profiles.calls == 0     # both stages served from disk
    assert not (tmp_path / "checkpoint").exists()           # cleaned up after success


def test_build_recomputes_when_the_plan_changes(tmp_path):
    cohort, matrix = _cohort(), _matrix()
    discovery, profiles = _FakeDiscovery(cohort), _FakeProfiles(matrix)
    builder = CohortBuilder(discovery, profiles, _FakeMetadata(), BiomFactory())
    request = Materialization(profile_sources=(Source.SRA_TAXONOMY,),
                              metadata_winning_source=Source.METALOG_METADATA)
    stale_key = checkpoint.cohort_key((SourceQuery(Source.SRA_METADATA, "SELECT 1"),))
    checkpoint.save_cohort(tmp_path, cohort, stale_key)
    checkpoint.save_matrix(tmp_path, matrix, checkpoint.matrix_key(stale_key, request.profile_sources))

    changed_queries = (SourceQuery(Source.SRA_METADATA, "SELECT 2"),)
    builder.build(changed_queries, request, out=None, plan_dir=tmp_path)

    assert discovery.calls == 1 and profiles.calls == 1     # stale checkpoint ignored
