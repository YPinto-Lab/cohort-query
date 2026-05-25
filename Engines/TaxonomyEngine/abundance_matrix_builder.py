from __future__ import annotations

import pandas as pd

from .abundance_matrix import AbundanceMatrix
from .nested_set_lineage_resolver import NestedSetLineageResolver

TAXON_KEY_SEP = "||"


class AbundanceMatrixBuilder:
    """Collapses a long taxonomy table to a single-rank, non-overlapping AbundanceMatrix."""

    def __init__(self) -> None:
        self._lineage_resolver = NestedSetLineageResolver()

    def build(self, taxonomy_df: pd.DataFrame, rank: str = "genus") -> AbundanceMatrix:
        rank_rows = self._rank_rows(taxonomy_df, rank)
        counts = self._counts(taxonomy_df, rank_rows, rank)
        lookup = self._lookup(rank_rows, rank)
        lineage_df = self._lineage_resolver.resolve(taxonomy_df)
        return AbundanceMatrix(counts=counts, lookup=lookup, lineage_df=lineage_df)

    def _rank_rows(self, taxonomy_df: pd.DataFrame, rank: str) -> pd.DataFrame:
        rows = taxonomy_df[taxonomy_df["rank"] == rank].copy()
        rows["taxon_key"] = (
            rows["rank"].astype(str) + TAXON_KEY_SEP
            + rows["name"].astype(str) + TAXON_KEY_SEP
            + rows["tax_id"].astype(str)
        )
        return rows

    def _counts(self, taxonomy_df: pd.DataFrame, rank_rows: pd.DataFrame, rank: str) -> pd.DataFrame:
        observations = pd.concat([self._resolved(rank_rows), self._unclassified(taxonomy_df, rank_rows, rank)])
        wide = observations.pivot_table(index="acc", columns="taxon_key", values="value", aggfunc="sum", fill_value=0)
        return wide.astype(int)

    def _resolved(self, rank_rows: pd.DataFrame) -> pd.DataFrame:
        grouped = rank_rows.groupby(["acc", "taxon_key"], as_index=False)["total_count"].sum()
        return grouped.rename(columns={"total_count": "value"})

    def _unclassified(self, taxonomy_df: pd.DataFrame, rank_rows: pd.DataFrame, rank: str) -> pd.DataFrame:
        sample_total = taxonomy_df.groupby("acc")["self_count"].sum()
        resolved_total = rank_rows.groupby("acc")["total_count"].sum()
        value = sample_total.subtract(resolved_total, fill_value=0)
        frame = value.reset_index(name="value")
        frame["taxon_key"] = f"Unclassified_{rank}"
        return frame[["acc", "taxon_key", "value"]]

    def _lookup(self, rank_rows: pd.DataFrame, rank: str) -> pd.DataFrame:
        taxa = rank_rows[["taxon_key", "tax_id", "rank", "name"]].drop_duplicates(subset=["taxon_key"])
        bucket = pd.DataFrame([{"taxon_key": f"Unclassified_{rank}", "tax_id": pd.NA, "rank": rank, "name": "Unclassified"}])
        return pd.concat([taxa, bucket], ignore_index=True)
