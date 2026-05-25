"""Taxonomy merge resolution utilities for historical NCBI tax IDs.

Biological context:
NCBI periodically merges deprecated tax IDs into active IDs. Historical SRA
records can still reference deprecated IDs. Without resolution, downstream
analysis may split counts across synonymous taxa and under-estimate abundance.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Tuple

import pandas as pd


class TaxonomyResolver:
    """Resolve deprecated tax IDs and re-aggregate counts by sample/taxon.

    This engine is pure computation: it receives a DataFrame and a pre-loaded
    merge dictionary, then returns a resolved DataFrame.
    """

    def __init__(self, merged_taxid_map: Mapping[int, int]):
        self._merged_taxid_map: Dict[int, int] = dict(merged_taxid_map)

    def resolve(
        self,
        taxonomy_df: pd.DataFrame,
        sample_col: str = "acc",
        tax_id_col: str = "tax_id",
        count_col: str = "total_count",
    ) -> pd.DataFrame:
        """Resolve ``tax_id`` values and aggregate duplicated sample/taxon rows.

        Resolution behavior:
        - If ``tax_id`` exists in ``merged.dmp`` map: replace with active tax ID.
        - If not found: keep original tax ID.
        - Rows missing sample or tax ID are dropped.

        Aggregation behavior:
        - Group by ``sample_col`` and resolved ``tax_id``.
        - Sum ``count_col``.
        - Keep one representative value for non-key metadata columns.
        """
        self._validate_required_columns(taxonomy_df, required=[sample_col, tax_id_col, count_col])

        if taxonomy_df.empty:
            return taxonomy_df.copy()

        working_df = taxonomy_df.copy()

        # Remove invalid key rows safely; downstream grouping requires both keys.
        working_df = working_df.dropna(subset=[sample_col, tax_id_col])
        if working_df.empty:
            return working_df

        numeric_tax_ids = pd.to_numeric(working_df[tax_id_col], errors="coerce")
        resolved_numeric = numeric_tax_ids.map(self._merged_taxid_map).fillna(numeric_tax_ids)

        resolved_tax_ids = working_df[tax_id_col].astype(str).str.strip()
        parseable_mask = numeric_tax_ids.notna()
        resolved_tax_ids.loc[parseable_mask] = (
            resolved_numeric.loc[parseable_mask].astype("Int64").astype(str)
        )
        working_df[tax_id_col] = resolved_tax_ids

        working_df[count_col] = pd.to_numeric(working_df[count_col], errors="coerce").fillna(0)

        group_keys = [sample_col, tax_id_col]
        grouped_counts = (
            working_df[group_keys + [count_col]]
            .groupby(group_keys, as_index=False)[count_col]
            .sum()
        )

        metadata_cols = [c for c in working_df.columns if c not in set(group_keys + [count_col])]
        if not metadata_cols:
            return grouped_counts

        representative_rows = (
            working_df.sort_values(by=count_col, ascending=False)
            .drop_duplicates(subset=[tax_id_col])[[tax_id_col] + metadata_cols]
        )

        merged_df = grouped_counts.merge(representative_rows, on=tax_id_col, how="left")
        ordered_cols = list(taxonomy_df.columns)
        return self._reorder_existing_columns(merged_df, ordered_cols)

    def summarize_resolution(
        self,
        taxonomy_df: pd.DataFrame,
        sample_col: str = "acc",
        tax_id_col: str = "tax_id",
        count_col: str = "total_count",
    ) -> Tuple[Dict[str, Any], pd.DataFrame]:
        """Return detailed resolution stats and old->new tax ID change rows.

        Returns:
            summary: aggregate counters for resolution impact.
            changes_df: one row per old->resolved tax ID pair with row/sample/count totals.
        """
        self._validate_required_columns(taxonomy_df, required=[sample_col, tax_id_col, count_col])

        if taxonomy_df.empty:
            empty_changes = pd.DataFrame(
                columns=["old_tax_id", "resolved_tax_id", "samples", "total_count_sum"]
            )
            return {
                "input_rows": 0,
                "rows_missing_keys": 0,
                "rows_considered": 0,
                "rows_with_numeric_tax_id": 0,
                "rows_with_non_numeric_tax_id": 0,
                "rows_updated": 0,
                "rows_unchanged": 0,
                "unique_old_tax_ids_updated": 0,
                "unique_resolved_tax_ids_touched": 0,
                "total_count_on_updated_rows": 0.0,
            }, empty_changes

        working_df = taxonomy_df.copy()
        input_rows = int(len(working_df))

        key_valid_mask = working_df[sample_col].notna() & working_df[tax_id_col].notna()
        rows_missing_keys = int((~key_valid_mask).sum())
        working_df = working_df.loc[key_valid_mask].copy()

        if working_df.empty:
            empty_changes = pd.DataFrame(
                columns=["old_tax_id", "resolved_tax_id", "samples", "total_count_sum"]
            )
            return {
                "input_rows": input_rows,
                "rows_missing_keys": rows_missing_keys,
                "rows_considered": 0,
                "rows_with_numeric_tax_id": 0,
                "rows_with_non_numeric_tax_id": 0,
                "rows_updated": 0,
                "rows_unchanged": 0,
                "unique_old_tax_ids_updated": 0,
                "unique_resolved_tax_ids_touched": 0,
                "total_count_on_updated_rows": 0.0,
            }, empty_changes

        numeric_tax_ids = pd.to_numeric(working_df[tax_id_col], errors="coerce")
        resolved_numeric = numeric_tax_ids.map(self._merged_taxid_map).fillna(numeric_tax_ids)
        parseable_mask = numeric_tax_ids.notna()
        updated_mask = parseable_mask & resolved_numeric.ne(numeric_tax_ids)

        old_tax_ids = working_df[tax_id_col].astype(str).str.strip()
        old_tax_ids.loc[parseable_mask] = numeric_tax_ids.loc[parseable_mask].astype("Int64").astype(str)

        resolved_tax_ids = old_tax_ids.copy()
        resolved_tax_ids.loc[parseable_mask] = resolved_numeric.loc[parseable_mask].astype("Int64").astype(str)

        counts = pd.to_numeric(working_df[count_col], errors="coerce").fillna(0)

        changes_working_df = pd.DataFrame(
            {
                "old_tax_id": old_tax_ids,
                "resolved_tax_id": resolved_tax_ids,
                "sample": working_df[sample_col].astype(str),
                "total_count": counts,
                "updated": updated_mask,
            }
        )

        changed_rows_df = changes_working_df[changes_working_df["updated"]].copy()
        if changed_rows_df.empty:
            changes_df = pd.DataFrame(
                columns=["old_tax_id", "resolved_tax_id", "samples", "total_count_sum"]
            )
        else:
            changes_df = (
                changed_rows_df.groupby(["old_tax_id", "resolved_tax_id"], as_index=False)
                .agg(
                    samples=("sample", "nunique"),
                    total_count_sum=("total_count", "sum"),
                )
                .sort_values(by=["total_count_sum", "samples"], ascending=False)
            )

        summary: Dict[str, Any] = {
            "input_rows": input_rows,
            "rows_missing_keys": rows_missing_keys,
            "rows_considered": int(len(working_df)),
            "rows_with_numeric_tax_id": int(parseable_mask.sum()),
            "rows_with_non_numeric_tax_id": int((~parseable_mask).sum()),
            "rows_updated": int(updated_mask.sum()),
            "rows_unchanged": int((~updated_mask).sum()),
            "unique_old_tax_ids_updated": int(changed_rows_df["old_tax_id"].nunique()) if not changed_rows_df.empty else 0,
            "unique_resolved_tax_ids_touched": int(changed_rows_df["resolved_tax_id"].nunique()) if not changed_rows_df.empty else 0,
            "total_count_on_updated_rows": float(changed_rows_df["total_count"].sum()) if not changed_rows_df.empty else 0.0,
        }

        return summary, changes_df

    @staticmethod
    def _validate_required_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
        missing = [col for col in required if col not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")

    @staticmethod
    def _reorder_existing_columns(df: pd.DataFrame, ordered_cols: Iterable[str]) -> pd.DataFrame:
        cols = [c for c in ordered_cols if c in df.columns]
        tail = [c for c in df.columns if c not in cols]
        return df[cols + tail]
