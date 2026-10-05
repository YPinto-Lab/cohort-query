"""CriterionResolver: SQL (buckets 1/2) unions with jattr_criteria's combined
result; jattr_criteria combine with EACH OTHER per jattr_combinator. Standalone
per-criterion counts always land in Cohort.jattr_matches, independent of the
combinator or the combined result -- see cohort.py's docstring."""
import duckdb
import pandas as pd
import pytest

from cohortquery.accession import Accession
from cohortquery.cohort import CriterionResolver, InvalidCohortQuery
from cohortquery.jattr_concepts import JattrMatch
from cohortquery.sources import Source
from cohortquery.translation import JattrCriterion, SourceQuery


class _FakeDatabase:
    def __init__(self, sql_result=(), raises=None):
        self._sql_result = sql_result
        self._raises = raises

    def query(self, sql, params=None):
        if self._raises is not None:
            raise self._raises
        return pd.DataFrame({"biosample": list(self._sql_result)})


class _FakeJattrIndex:
    """Stands in for JattrConceptIndex: returns a fixed matches dict regardless
    of the actual criteria/embedding, keyed by concept."""

    def __init__(self, matches: dict[str, list[JattrMatch]]):
        self._matches = matches

    def matching(self, criteria):
        return {criterion.concept: self._matches.get(criterion.concept, [])
                for criterion in criteria}


def _match(concept, matched_on, *samples):
    return JattrMatch(concept=concept, matched_on=matched_on,
                      biosamples=frozenset(Accession(s) for s in samples))


def test_sql_only_query_behaves_exactly_like_the_old_mechanism():
    resolver = CriterionResolver(_FakeDatabase(sql_result=["SAMN001", "SAMN002"]),
                                 _FakeJattrIndex({}))

    cohort = resolver.discover((SourceQuery(Source.SRA_METADATA, "SELECT biosample ..."),))

    assert cohort.by_source[Source.SRA_METADATA] == {Accession("SAMN001"), Accession("SAMN002")}
    assert cohort.jattr_matches == {}


def test_jattr_only_query_needs_no_sql():
    matches = {"IBD": [_match("IBD", "ibd_sam", "SAMN001")]}
    resolver = CriterionResolver(_FakeDatabase(), _FakeJattrIndex(matches))
    query = SourceQuery(Source.SRA_METADATA, sql=None,
                        jattr_criteria=(JattrCriterion(concept="IBD"),))

    cohort = resolver.discover((query,))

    assert cohort.by_source[Source.SRA_METADATA] == {Accession("SAMN001")}


def test_any_combinator_unions_distinct_concepts():
    """"IBD" (35,000) and "calprotectin" (5,000), zero overlap -- "any" must
    return the union, nobody silently dropped."""
    matches = {
        "IBD": [_match("IBD", "ibd_sam", "SAMN001", "SAMN002")],
        "calprotectin measurement": [_match("calprotectin measurement",
                                            "calprotectin_sam", "SAMN003")],
    }
    resolver = CriterionResolver(_FakeDatabase(), _FakeJattrIndex(matches))
    query = SourceQuery(Source.SRA_METADATA, sql=None,
                        jattr_criteria=(JattrCriterion(concept="IBD"),
                                       JattrCriterion(concept="calprotectin measurement")),
                        jattr_combinator="any")

    cohort = resolver.discover((query,))

    assert cohort.by_source[Source.SRA_METADATA] == {
        Accession("SAMN001"), Accession("SAMN002"), Accession("SAMN003")}


def test_all_combinator_can_genuinely_return_empty():
    """The true answer to an AND the data does not support is 0 -- never
    silently softened to a union or to picking one criterion."""
    matches = {
        "IBD": [_match("IBD", "ibd_sam", "SAMN001", "SAMN002")],
        "calprotectin measurement": [_match("calprotectin measurement",
                                            "calprotectin_sam", "SAMN003")],
    }
    resolver = CriterionResolver(_FakeDatabase(), _FakeJattrIndex(matches))
    query = SourceQuery(Source.SRA_METADATA, sql=None,
                        jattr_criteria=(JattrCriterion(concept="IBD"),
                                       JattrCriterion(concept="calprotectin measurement")),
                        jattr_combinator="all")

    cohort = resolver.discover((query,))

    assert cohort.by_source[Source.SRA_METADATA] == frozenset()


def test_standalone_counts_survive_an_empty_all_combination():
    """The whole point of jattr_matches: a 0 combined result is never a silent
    dead end -- each criterion's own reach is still visible."""
    matches = {
        "IBD": [_match("IBD", "ibd_sam", "SAMN001", "SAMN002")],
        "calprotectin measurement": [_match("calprotectin measurement",
                                            "calprotectin_sam", "SAMN003")],
    }
    resolver = CriterionResolver(_FakeDatabase(), _FakeJattrIndex(matches))
    query = SourceQuery(Source.SRA_METADATA, sql=None,
                        jattr_criteria=(JattrCriterion(concept="IBD"),
                                       JattrCriterion(concept="calprotectin measurement")),
                        jattr_combinator="all")

    cohort = resolver.discover((query,))

    per_concept = cohort.jattr_matches[Source.SRA_METADATA]
    assert len(per_concept["IBD"][0].biosamples) == 2
    assert len(per_concept["calprotectin measurement"][0].biosamples) == 1


def test_bucket_2_sql_and_jattr_always_union_regardless_of_combinator():
    """collection_date_sam-style redundant field: sql's result and jattr_criteria's
    combined result union -- a separate rule from jattr_combinator, which only
    governs jattr_criteria among EACH OTHER."""
    matches = {"collection date": [_match("collection date", "collection_date_sam", "SAMN002")]}
    resolver = CriterionResolver(_FakeDatabase(sql_result=["SAMN001"]), _FakeJattrIndex(matches))
    query = SourceQuery(Source.SRA_METADATA, "SELECT biosample ...",
                        jattr_criteria=(JattrCriterion(concept="collection date"),))

    cohort = resolver.discover((query,))

    assert cohort.by_source[Source.SRA_METADATA] == {Accession("SAMN001"), Accession("SAMN002")}


def test_bad_sql_raises_invalid_cohort_query():
    resolver = CriterionResolver(_FakeDatabase(raises=duckdb.BinderException("boom")),
                                 _FakeJattrIndex({}))

    with pytest.raises(InvalidCohortQuery):
        resolver.discover((SourceQuery(Source.SRA_METADATA, "SELECT bogus"),))
