"""on_step lets a caller (the SLURM worker) log which phase is running, without
CohortBuilder knowing anything about logging or SLURM."""
import cohortquery
from cohortquery.adapters import CannedLlmBackend, DuckDbConnection
from cohortquery.translation import SourceQuery, Translation

from fixtures.mirror import build_fixture_mirror

TRANSLATION = Translation(
    interpretation="gut metagenomes",
    queries=(SourceQuery(cohortquery.Source.METALOG_METADATA,
                         "SELECT * FROM metalog_metadata"),))


class _EmbedderThatMustNotBeCalled:
    """TRANSLATION has no jattr_criteria, so a correct CriterionResolver never
    calls embed() at all -- this proves it, rather than silently degrading."""

    def embed(self, texts):
        raise AssertionError("embed() called with no jattr_criteria present")


def test_on_step_is_called_for_each_phase_in_order(tmp_path):
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    cohortquery.config(db=path, database=connection, backend=CannedLlmBackend(TRANSLATION))
    plan = cohortquery.ask("gut metagenomes")
    seen = []

    plan.run(profile_sources=cohortquery.Source.METALOG_MOTUS3, on_step=seen.append)

    # ask() now discovers and caches the cohort onto the plan, so run() reuses it.
    assert seen == ["discovering cohort (cached)", "reading profile matrix",
                    "assembling and writing biom"]
    connection.close()


def test_on_step_defaults_to_doing_nothing(tmp_path):
    """Every existing caller of Plan.run passes no on_step -- this must not break."""
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    cohortquery.config(db=path, database=connection, backend=CannedLlmBackend(TRANSLATION))
    plan = cohortquery.ask("gut metagenomes")

    table, report = plan.run(profile_sources=cohortquery.Source.METALOG_MOTUS3)

    assert report.biosamples > 0
    connection.close()


def test_a_cached_cohort_skips_rediscovery_and_gets_a_distinct_label(tmp_path):
    """Passing bad SQL as `queries` proves the cached path is really taken, not
    just labeled that way: if discover() ran anyway, it would raise on the bogus
    table before this test could ever reach its assertions."""
    from cohortquery import runtime
    from cohortquery.build import Materialization
    from cohortquery.cohort import CriterionResolver
    from cohortquery.jattr_concepts import JattrConceptIndex

    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    cohortquery.config(db=path, database=connection, backend=CannedLlmBackend(TRANSLATION))
    plan = cohortquery.ask("gut metagenomes")
    jattr = JattrConceptIndex(connection, embedder=_EmbedderThatMustNotBeCalled())
    cohort = CriterionResolver(connection, jattr).discover(plan.translation.queries)
    poisoned_queries = (SourceQuery(cohortquery.Source.METALOG_METADATA,
                                    "SELECT * FROM no_such_table_at_all"),)
    request = Materialization(profile_sources=(cohortquery.Source.METALOG_MOTUS3,),
                              metadata_winning_source=cohortquery.Source.METALOG_METADATA)
    seen = []

    table, report = runtime.cohort_builder().build(
        poisoned_queries, request, None, on_step=seen.append, discovered=cohort)

    assert seen[0] == "discovering cohort (cached)"
    # report.dropped is cohort.union() - matrix.biosamples(); this only adds up if
    # the build actually used the passed-in cached cohort's 14 biosamples, not some
    # other (e.g. empty) cohort.
    assert report.biosamples + len(report.dropped) == len(cohort.union())
    connection.close()
