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

from askslm.accession import Accession
from askslm.concept_search import Embedder
from askslm.translation import JattrCriterion

# Plain top-N per table, no distance cutoff -- same placeholder-not-yet-tuned
# situation as concept_search.py's TOP_K_VALUES. Calibrating this against a real
# distance threshold is explicitly deferred in the design note until the tables
# exist and can be tested against, which they now do -- revisit with real data.
TOP_K = 5


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
        return self._indexes.keys_table.search(vector).limit(TOP_K).to_pandas()

    def _nearest_values(self, vector: list[float]) -> pd.DataFrame:
        return self._indexes.values_table.search(vector).limit(TOP_K).to_pandas()
