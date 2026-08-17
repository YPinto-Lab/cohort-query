"""Metadata reconciliation: the winner wins, the other fills gaps per field.

With two metadata sources there is no precedence table to build -- the winner
fully determines the result and the single other source has no peer to tie with.
A third source is the only thing that would reintroduce an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import reduce

import pandas as pd

from askslm.cohort import Accession, Cohort, key_column
from askslm.ports import Database
from askslm.sources import Source


@dataclass(frozen=True)
class ReconciledMetadata:
    frame: pd.DataFrame                    # indexed by Accession. NEVER merged with lineage.

    def restricted_to(self, accessions: frozenset[Accession]) -> "ReconciledMetadata":
        present = [key for key in sorted(accessions) if key in self.frame.index]
        return ReconciledMetadata(self.frame.loc[present])


class MetadataReader:
    """Reads ONE metadata source for the cohort -- the mirror of ProfileReader."""

    def __init__(self, database: Database):
        self._database = database

    def read(self, source: Source, accessions: frozenset[Accession]) -> pd.DataFrame:
        keys = ", ".join(f"'{key}'" for key in sorted(accessions)) or "''"
        table = source.spec().table
        rows = self._database.query(
            f"SELECT * FROM {table} WHERE {self._key_expression(table)} IN ({keys})")
        if rows.empty:
            return pd.DataFrame()
        frame = rows.copy()
        frame.index = key_column(frame)
        return frame[~frame.index.duplicated()]

    def _key_expression(self, table: str) -> str:
        return "coalesce(biosample, sample_alias)" if table.startswith("metalog_") else "biosample"


class MetadataReconciler:
    def __init__(self, reader: MetadataReader):
        self._reader = reader

    def reconciled(self, cohort: Cohort, winning_source: Source) -> ReconciledMetadata:
        accessions = cohort.union()
        winner = self._reader.read(winning_source, accessions)
        others = [self._reader.read(source, accessions)
                  for source in cohort.by_source if source is not winning_source]
        return ReconciledMetadata(reduce(combine_first_onto, others, winner))


def combine_first_onto(winner: pd.DataFrame, other: pd.DataFrame) -> pd.DataFrame:
    """Exactly 'left wins, right fills the gaps' -- per field, not per row."""
    if other.empty:
        return winner
    if winner.empty:
        return other
    return winner.combine_first(other)
