"""A JattrCriterion's concept -> the biosamples it matches, by embedding similarity
against attribute_keys_index (PRESENCE: has this field at all, any value?) and
attribute_values_index (CONTENT: has a value that means this, under any key).

Both tables are searched for every concept and the hits unioned -- "calprotectin
measurement" naturally lands on calprotectin-named KEYS, "IBD" naturally lands on
IBD-meaning VALUES, and a concept is never forced to declare which kind it is
upfront (recall-first: a concept the wrong-table search misses costs nothing, one
the right-table search would have missed by guessing wrong costs a silently
absent criterion). See the "Inverted Index Plan" design note.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from cohortquery.accession import Accession
from cohortquery.concept_search import Embedder
from cohortquery.translation import JattrCriterion

# Calibrated 2026-10-08 against the real attribute_keys_index/attribute_values_index
# (85,143 keys / 14,098,043 values) by probing 5 concepts' real distance curves out
# to rank 300: true synonyms form a dense, CONCEPT-DEPENDENT cluster with no
# universal elbow -- some concepts (antibiotic exposure, host age, sample collection
# date) stay legitimately on-topic past rank 300, others (calprotectin measurement)
# drift into clear noise by ~0.86. A small fixed top-N (the prior TOP_K=5) can't
# tell "still relevant, just crowded by near-duplicate naming" from "genuinely
# exhausted" -- this is exactly how fecalcalprotectin_run (rank 27, distance 0.817)
# was silently dropped despite being a real match. DISTANCE_THRESHOLD lets a
# concept's true neighborhood be as wide or narrow as the data actually supports;
# MAX_CANDIDATES is the safety cap a pure threshold doesn't provide on its own,
# bounding cost/precision for dense generic concepts (dates, host age) that would
# otherwise match hundreds of keys.
DISTANCE_THRESHOLD = 0.82
MAX_CANDIDATES = 50


@dataclass(frozen=True)
class LanceAttributeIndexes:
    """The two Lance tables JattrConceptIndex searches -- keys (PRESENCE) and
    values (CONTENT). Bundled so the constructor stays at one collaborator
    instead of two positionally-similar table handles."""
    keys_table: Any
    values_table: Any


@dataclass(frozen=True)
class JattrMatch:
    concept: str                        # the criterion this match came from
    matched_on: str                     # the actual key or value found in the data
    biosamples: frozenset[Accession]


class JattrConceptIndex:
    def __init__(self, indexes: LanceAttributeIndexes, embedder: Embedder):
        self._indexes = indexes
        self._embedder = embedder

    def matching(self, criteria: tuple[JattrCriterion, ...]) -> dict[str, list[JattrMatch]]:
        """concept -> its JattrMatch list. One embed() call for every criterion's
        concept at once -- the "one live call per ask()" design commits to,
        regardless of how many jattr-touching criteria a question has."""
        if not criteria:
            return {}
        vectors = self._embedder.embed([criterion.concept for criterion in criteria])
        return {criterion.concept: self._matches_for(criterion.concept, vector)
                for criterion, vector in zip(criteria, vectors)}

    def _matches_for(self, concept: str, vector: list[float]) -> list[JattrMatch]:
        key_matches = [self._match(concept, row.key, row.biosample)
                      for row in self._nearest_keys(vector).itertuples(index=False)]
        value_matches = [self._match(concept, row.value, row.biosample)
                         for row in self._nearest_values(vector).itertuples(index=False)]
        return key_matches + value_matches

    def _match(self, concept: str, matched_on: str, biosamples: list[str]) -> JattrMatch:
        return JattrMatch(concept=concept, matched_on=matched_on,
                          biosamples=frozenset(Accession(sample) for sample in biosamples))

    def _nearest_keys(self, vector: list[float]) -> pd.DataFrame:
        return self._within_threshold(self._indexes.keys_table.search(vector))

    def _nearest_values(self, vector: list[float]) -> pd.DataFrame:
        return self._within_threshold(self._indexes.values_table.search(vector))

    def _within_threshold(self, search) -> pd.DataFrame:
        candidates = search.limit(MAX_CANDIDATES).to_pandas()
        return candidates[candidates["_distance"] <= DISTANCE_THRESHOLD]
