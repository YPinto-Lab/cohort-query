from __future__ import annotations

from functools import singledispatchmethod

import pandas as pd

from .abundance_matrix import AbundanceMatrix
from .nested_set_lineage_resolver import NestedSetLineageResolver

TAXON_KEY_SEP = "||"


class AbundanceMatrixBuilder:
    """Builds AbundanceMatrix from a taxonomy DataFrame or collapses an existing matrix to a rank."""

    def __init__(self) -> None:
        self._lineage_resolver = NestedSetLineageResolver()

    @singledispatchmethod
    def build(self, source, *args, **kwargs) -> AbundanceMatrix:
        raise TypeError(f"Cannot build AbundanceMatrix from {type(source).__name__}")

    @build.register
    def _build_from_taxonomy(self, taxonomy_df: pd.DataFrame) -> AbundanceMatrix:
        rows = self._rows_with_taxon_key(taxonomy_df)
        matrix = self._pivot_self_counts(rows)
        total_reads = matrix.sum(axis=1)
        taxon_key_lookup = self._lookup_from_rows(rows)
        tax_id_lineage_lookup = self._lineage_resolver.resolve(taxonomy_df)
        return AbundanceMatrix(matrix, total_reads, taxon_key_lookup, tax_id_lineage_lookup)

    @build.register
    def _build_from_matrix(self, source: AbundanceMatrix, rank: str) -> AbundanceMatrix:
        column_to_ancestor = self._column_to_rank_ancestor(source, rank)
        kept = self._kept_columns(source.matrix, column_to_ancestor)
        grouped = self._collapse_columns(source.matrix, kept, column_to_ancestor)
        new_matrix = self._rekey_to_taxon_keys(grouped, source._taxon_key_lookup, rank)
        total_reads = new_matrix.sum(axis=1)
        new_lookup = self._rank_lookup(source._taxon_key_lookup, rank, new_matrix.columns)
        return AbundanceMatrix(new_matrix, total_reads, new_lookup, source._tax_id_lineage_lookup)

    def _rows_with_taxon_key(self, taxonomy_df: pd.DataFrame) -> pd.DataFrame:
        rows = taxonomy_df.copy()
        rows["taxon_key"] = (
            rows["rank"].astype(str) + TAXON_KEY_SEP
            + rows["name"].astype(str) + TAXON_KEY_SEP
            + rows["tax_id"].astype(str)
        )
        return rows

    def _pivot_self_counts(self, rows: pd.DataFrame) -> pd.DataFrame:
        wide = rows.pivot_table(
            index="acc", columns="taxon_key", values="self_count",
            aggfunc="sum", fill_value=0,
        )
        return wide.astype(int)

    def _lookup_from_rows(self, rows: pd.DataFrame) -> pd.DataFrame:
        return rows[["taxon_key", "tax_id", "rank", "name"]].drop_duplicates(subset=["taxon_key"]).reset_index(drop=True)

    def _column_to_rank_ancestor(self, source: AbundanceMatrix, rank: str) -> dict[str, str | None]:
        lookup = self._numeric_tax_id(source._taxon_key_lookup[["taxon_key", "tax_id"]])
        lineage = self._numeric_tax_id(source._tax_id_lineage_lookup[["tax_id", rank]])
        ancestor = lookup.merge(lineage, on="tax_id", how="left").set_index("taxon_key")[rank]
        return {key: value if isinstance(value, str) else None for key, value in ancestor.items()}

    def _numeric_tax_id(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        frame["tax_id"] = pd.to_numeric(frame["tax_id"], errors="coerce")
        return frame

    def _kept_columns(self, matrix: pd.DataFrame, ancestors: dict[str, str | None]) -> list[str]:
        return [c for c in matrix.columns if ancestors.get(c) is not None]

    def _collapse_columns(
        self,
        matrix: pd.DataFrame,
        kept: list[str],
        ancestors: dict[str, str | None],
    ) -> pd.DataFrame:
        if not kept:
            return pd.DataFrame(index=matrix.index)
        ancestor_map = {c: ancestors[c] for c in kept}
        renamed = matrix[kept].rename(columns=ancestor_map)
        return renamed.T.groupby(level=0).sum().T.astype(int)

    def _rekey_to_taxon_keys(
        self,
        grouped: pd.DataFrame,
        full_lookup: pd.DataFrame,
        rank: str,
    ) -> pd.DataFrame:
        rank_rows = full_lookup[full_lookup["rank"] == rank].drop_duplicates(subset=["name"]).set_index("name")
        rename = {name: rank_rows.loc[name, "taxon_key"] for name in grouped.columns if name in rank_rows.index}
        return grouped.rename(columns=rename)

    def _rank_lookup(
        self,
        full_lookup: pd.DataFrame,
        rank: str,
        taxon_keys: pd.Index,
    ) -> pd.DataFrame:
        rank_rows = full_lookup[full_lookup["rank"] == rank]
        return rank_rows[rank_rows["taxon_key"].isin(list(taxon_keys))].reset_index(drop=True)
