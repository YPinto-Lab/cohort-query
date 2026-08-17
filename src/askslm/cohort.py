"""The sample key and the SRA / Metalog / shared partition. Pure set logic.

There is no run-time normalizer: `biosample` is stamped onto every table at
build, so every query already returns the key. The one exception is the Metalog
orphan tail, which has no BioSample and stays addressable by `sample_alias` --
the fallback the column-id rule already had (HLD B.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NewType

import pandas as pd

from askslm.ports import Database
from askslm.sources import Source
from askslm.translation import SourceQuery

Accession = NewType("Accession", str)


@dataclass(frozen=True)
class Cohort:
    by_source: dict[Source, frozenset[Accession]]      # METADATA sources only

    def union(self) -> frozenset[Accession]:
        return frozenset().union(*self.by_source.values()) if self.by_source else frozenset()

    def shared(self) -> frozenset[Accession]:
        return frozenset(key for key in self.union() if self._appearances(key) > 1)

    def only(self, source: Source) -> frozenset[Accession]:
        others = self.union() - self.by_source[source]
        return self.by_source[source] - others

    def _appearances(self, key: Accession) -> int:
        return sum(1 for keys in self.by_source.values() if key in keys)


class CohortDiscovery:
    """Runs each metadata query and groups the returned keys by source."""

    def __init__(self, database: Database):
        self._database = database

    def discover(self, queries: tuple[SourceQuery, ...]) -> Cohort:
        return Cohort({query.source: self._keys(query) for query in queries})

    def _keys(self, query: SourceQuery) -> frozenset[Accession]:
        return accessions_of(self._database.query(query.sql))


def accessions_of(frame: pd.DataFrame) -> frozenset[Accession]:
    """A row's key is its biosample, falling back to sample_alias for the orphan tail."""
    return frozenset(Accession(key) for key in key_column(frame) if key)


def key_column(frame: pd.DataFrame) -> pd.Series:
    if "sample_alias" in frame.columns and "biosample" in frame.columns:
        return frame["biosample"].fillna(frame["sample_alias"])
    if "biosample" in frame.columns:
        return frame["biosample"].dropna()
    return frame["sample_alias"]
