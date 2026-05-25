from __future__ import annotations

import pandas as pd

from .abundance_matrix import AbundanceMatrix
from .nested_set_lineage_resolver import NestedSetLineageResolver

TAXON_KEY_SEP = "||"


class AbundanceMatrixBuilder:
    """Pivots a long taxonomy table into an AbundanceMatrix with lineage."""

    def __init__(self) -> None:
        self._lineage_resolver = NestedSetLineageResolver()

    def build(self, taxonomy_df: pd.DataFrame) -> AbundanceMatrix:
        keyed = self._with_taxon_key(taxonomy_df)
        counts = self._pivot_counts(keyed)
        lookup = self._build_lookup(keyed)
        lineage_df = self._lineage_resolver.resolve(taxonomy_df)
        return AbundanceMatrix(counts=counts, lookup=lookup, lineage_df=lineage_df)

    def _with_taxon_key(self, taxonomy_df: pd.DataFrame) -> pd.DataFrame:
        keyed = taxonomy_df.copy()
        keyed["taxon_key"] = (
            keyed["rank"].astype(str) + TAXON_KEY_SEP
            + keyed["name"].astype(str) + TAXON_KEY_SEP
            + keyed["tax_id"].astype(str)
        )
        return keyed

    def _pivot_counts(self, keyed: pd.DataFrame) -> pd.DataFrame:
        grouped = keyed.groupby(["acc", "taxon_key"], as_index=False)["total_count"].sum()
        wide = grouped.pivot(index="acc", columns="taxon_key", values="total_count").fillna(0)
        return wide.astype(int)

    def _build_lookup(self, keyed: pd.DataFrame) -> pd.DataFrame:
        columns = ["taxon_key", "tax_id", "rank", "name"]
        return keyed[columns].drop_duplicates(subset=["taxon_key"]).reset_index(drop=True)
