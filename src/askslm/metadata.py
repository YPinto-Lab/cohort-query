"""Metadata reconciliation: the winner wins, the other fills gaps per field.

With two metadata sources there is no precedence table to build -- the winner
fully determines the result and the single other source has no peer to tie with.
A third source is the only thing that would reintroduce an order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import reduce

import pandas as pd

from askslm.cohort import Accession, Cohort, key_column
from askslm.ports import Database
from askslm.sources import Source


@dataclass(frozen=True)
class ReconciledMetadata:
    frame: pd.DataFrame                    # indexed by Accession. NEVER merged with lineage.
    covering_columns: dict[Accession, frozenset[str]] = field(default_factory=dict)
    """Which columns a given accession's row is actually backed by.

    `combine_first` unions BOTH sources' columns onto every row, so a biosample that
    exists only in SRA_METADATA still gets every METALOG_METADATA column -- as an
    explicit null, not an absence. That is wrong: those fields were never looked up for
    this sample, not looked up and found empty. This is the per-row provenance that lets
    the biom writer drop them instead of stamping a foreign schema onto every sample.
    """

    def restricted_to(self, accessions: frozenset[Accession]) -> "ReconciledMetadata":
        present = [key for key in sorted(accessions) if key in self.frame.index]
        return ReconciledMetadata(self.frame.loc[present],
                                 {key: self.covering_columns[key] for key in present
                                  if key in self.covering_columns})

    def columns_for(self, accession: Accession) -> frozenset[str] | None:
        """None means unrestricted -- e.g. a fixture ReconciledMetadata built by hand
        with no provenance tracked. Never silently hides real fields in that case."""
        return self.covering_columns.get(accession)


class MetadataReader:
    """Reads ONE metadata source for the cohort -- the mirror of ProfileReader."""

    def __init__(self, database: Database):
        self._database = database

    def read(self, source: Source, accessions: frozenset[Accession]) -> pd.DataFrame:
        table = source.spec().table
        rows = self._database.query(
            f"SELECT * FROM {table} "
            f"WHERE {self._key_expression(table)} IN (SELECT unnest(?::VARCHAR[]))",
            [sorted(accessions)])
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
        """Each source is read for exactly the accessions ITS OWN discovery query
        confirmed (`cohort.by_source[source]`), never the whole `cohort.union()`.

        A biosample discovered only by SRA_METADATA may still have some unrelated row
        in metalog_metadata -- a different study, never checked against this question's
        criteria. Reading METALOG_METADATA against the full union would merge that
        unconfirmed row in anyway. Scoping each read to what that source itself vetted
        is what makes `Cohort.shared() == 0` actually mean zero cross-source blending.
        """
        frames = {source: self._reader.read(source, keys) for source, keys in cohort.by_source.items()}
        if winning_source not in frames:
            # The prompt can now omit a metadata source's query entirely (partial
            # criterion coverage), so the configured winner may simply not have run
            # -- fall back to whichever metadata source did, since with it absent
            # there is no peer left to prefer over.
            winning_source = next(iter(frames))
        others = [frame for source, frame in frames.items() if source is not winning_source]
        combined = reduce(combine_first_onto, others, frames[winning_source])
        return ReconciledMetadata(combined, _covering_columns(frames))


def combine_first_onto(winner: pd.DataFrame, other: pd.DataFrame) -> pd.DataFrame:
    """Exactly 'left wins, right fills the gaps' -- per field, not per row."""
    if other.empty:
        return winner
    if winner.empty:
        return other
    return winner.combine_first(other)


def _covering_columns(frames: dict[Source, pd.DataFrame]) -> dict[Accession, frozenset[str]]:
    covering: dict[Accession, set[str]] = {}
    for frame in frames.values():
        columns = frozenset(frame.columns)
        for accession in frame.index:
            covering.setdefault(accession, set()).update(columns)
    return {accession: frozenset(columns) for accession, columns in covering.items()}
