"""The sample key and the SRA / Metalog / shared partition. Pure set logic.

There is no run-time normalizer: `biosample` is stamped onto every table at
build, so every query already returns the key. The one exception is the Metalog
orphan tail, which has no BioSample and stays addressable by `sample_alias` --
the fallback the column-id rule already had (HLD B.3).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import duckdb
import pandas as pd

from cohortquery.accession import Accession
from cohortquery.jattr_concepts import JattrConceptIndex, JattrMatch
from cohortquery.ports import Database
from cohortquery.sources import Source
from cohortquery.translation import SourceQuery


class InvalidCohortQuery(RuntimeError):
    """A metadata source's LLM-authored SQL failed against the mirror.

    A sanctioned validation boundary: the model's SQL is untrusted input, so it is
    the one place a database error is caught rather than left to crash ask() (HLD H.1).
    Distinct from Translation.failure, which is the model declining to translate at
    all -- this is SQL DuckDB itself rejects, e.g. ILIKE against a numeric column.
    """

    def __init__(self, source: Source, message: str):
        super().__init__(f"{source.name}: {message}")
        self.source = source
        self.message = message      # the raw database text, for the repair prompt


@dataclass(frozen=True)
class Cohort:
    by_source: dict[Source, frozenset[Accession]]      # METADATA sources only
    # per source, per JattrCriterion.concept -> its own standalone matches,
    # independent of how jattr_combinator combined it into by_source. This is
    # what the explain/BioProject-rollup layer reads: "IBD alone: 35,000" even
    # when the combined cohort (an "all" combinator) is 0.
    jattr_matches: dict[Source, dict[str, list[JattrMatch]]] = field(default_factory=dict)

    def union(self) -> frozenset[Accession]:
        return frozenset().union(*self.by_source.values()) if self.by_source else frozenset()

    def shared(self) -> frozenset[Accession]:
        return frozenset(key for key in self.union() if self._appearances(key) > 1)

    def only(self, source: Source) -> frozenset[Accession]:
        others = self.union() - self.by_source[source]
        return self.by_source[source] - others

    def _appearances(self, key: Accession) -> int:
        return sum(1 for keys in self.by_source.values() if key in keys)


class CriterionResolver:
    """Runs each metadata query and groups the resulting biosamples by source.

    A SourceQuery mixes up to two independent things: SQL against native columns
    (buckets 1/2) and JattrCriterion concepts resolved via nearest-neighbor lookup
    against attribute_keys_index/attribute_values_index (buckets 2/3). Two
    separate combination rules, not in conflict:
      - sql's result UNIONS with jattr_criteria's combined result -- bucket 2's
        same-fact-recorded-twice case (e.g. collection_date_sam).
      - jattr_criteria combine with EACH OTHER per query.jattr_combinator:
        "all" intersects (can genuinely be empty -- that is the true answer to
        an AND the data does not support, not something to silently soften),
        "any" unions. Either way, each criterion's own standalone reach is kept
        in Cohort.jattr_matches regardless of the combinator or the combined
        result, so an empty "all" is never a silent dead end.
    """

    def __init__(self, database: Database, jattr: JattrConceptIndex):
        self._database = database
        self._jattr = jattr

    def discover(self, queries: tuple[SourceQuery, ...]) -> Cohort:
        by_source = {}
        jattr_matches = {}
        for query in queries:
            matches = self._jattr.matching(query.jattr_criteria)
            by_source[query.source] = self._resolve(query, matches)
            if matches:
                jattr_matches[query.source] = matches
        return Cohort(by_source, jattr_matches)

    def _resolve(self, query: SourceQuery, matches: dict[str, list[JattrMatch]]
                ) -> frozenset[Accession]:
        sql_result = self._run_sql(query) if query.sql else frozenset()
        return sql_result | self._combined(query.jattr_combinator, matches)

    def _run_sql(self, query: SourceQuery) -> frozenset[Accession]:
        try:
            frame = self._database.query(query.sql)
        except duckdb.Error as error:
            raise InvalidCohortQuery(query.source, str(error)) from error
        return accessions_of(frame)

    def _combined(self, combinator: str, matches: dict[str, list[JattrMatch]]
                 ) -> frozenset[Accession]:
        if not matches:
            return frozenset()
        sets = [_standalone(concept_matches) for concept_matches in matches.values()]
        if combinator == "all":
            return frozenset.intersection(*sets)
        return frozenset().union(*sets)


def _standalone(matches: list[JattrMatch]) -> frozenset[Accession]:
    return frozenset().union(*(match.biosamples for match in matches)) if matches else frozenset()


def accessions_of(frame: pd.DataFrame) -> frozenset[Accession]:
    """A row's key is its biosample, falling back to sample_alias for the orphan tail."""
    return frozenset(Accession(key) for key in key_column(frame) if key)


def key_column(frame: pd.DataFrame) -> pd.Series:
    if "sample_alias" in frame.columns and "biosample" in frame.columns:
        return frame["biosample"].fillna(frame["sample_alias"])
    if "biosample" in frame.columns:
        return frame["biosample"].dropna()
    return frame["sample_alias"]
