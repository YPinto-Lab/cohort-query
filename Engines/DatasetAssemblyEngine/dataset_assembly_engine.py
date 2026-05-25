"""Pure matrix artifact computation functions.

These helpers contain only DataFrame transformations and do not perform file I/O.
They are used by runner orchestration methods that own artifact writes.
"""

from __future__ import annotations

from typing import List, Tuple

import pandas as pd


def compute_taxonomy_matrices(
    taxonomy_df: pd.DataFrame,
    taxon_key_sep: str = "||",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Build taxonomy-stage outputs from canonical taxonomy input.

    Returns:
        abundance_matrix: sample x taxon_key matrix of total_count values.
        taxon_lookup_df: one row per taxon_key with rank/name/tax_id and lineage columns when present.
    """
    lineage_columns = [c for c in ["ileft", "iright"] if c in taxonomy_df.columns]

    taxonomy_for_wide = taxonomy_df[["acc", "tax_id", "rank", "name", "total_count"] + lineage_columns].copy()
    taxonomy_for_wide["taxon_key"] = (
        taxonomy_for_wide["rank"].astype(str)
        + taxon_key_sep
        + taxonomy_for_wide["name"].astype(str)
        + taxon_key_sep
        + taxonomy_for_wide["tax_id"].astype(str)
    )
    taxonomy_for_wide = (
        taxonomy_for_wide[["acc", "taxon_key", "total_count"]]
        .groupby(["acc", "taxon_key"], as_index=False)["total_count"]
        .sum()
    )

    abundance_matrix = taxonomy_for_wide.pivot(index="acc", columns="taxon_key", values="total_count").fillna(0)
    abundance_matrix = abundance_matrix.astype(int)

    lookup_base = taxonomy_df[["tax_id", "rank", "name"] + lineage_columns].copy()
    lookup_base["taxon_key"] = (
        lookup_base["rank"].astype(str)
        + taxon_key_sep
        + lookup_base["name"].astype(str)
        + taxon_key_sep
        + lookup_base["tax_id"].astype(str)
    )
    taxon_lookup_columns = ["taxon_key", "rank", "name", "tax_id"] + lineage_columns
    taxon_lookup_df = lookup_base[taxon_lookup_columns].drop_duplicates(subset=["taxon_key"])

    return abundance_matrix, taxon_lookup_df


def compute_analysis_wide_dataset(
    enriched_metadata_df: pd.DataFrame,
    abundance_matrix: pd.DataFrame,
) -> Tuple[pd.DataFrame, List[str]]:
    """Build the merged analysis-wide dataset from enriched metadata and abundance features.

    Returns:
        abundance_metadata_matrix: enriched metadata + taxa feature columns.
        metadata_columns: ordered metadata columns captured before joining taxa features.
    """
    metadata_columns = list(enriched_metadata_df.columns)

    abundance_features = abundance_matrix.copy()
    abundance_features.index.name = "acc"
    merged = enriched_metadata_df.set_index("acc", drop=False).join(abundance_features, how="left")
    abundance_metadata_matrix = merged.reset_index(drop=True)

    taxa_feature_columns = list(abundance_features.columns)
    abundance_metadata_matrix[taxa_feature_columns] = abundance_metadata_matrix[taxa_feature_columns].fillna(0)

    return abundance_metadata_matrix, metadata_columns


def compute_maaslin_export(
    abundance_matrix: pd.DataFrame,
    taxon_lookup_df: pd.DataFrame,
    sample_col: str = "acc",
) -> pd.DataFrame:
    """Build a MaAsLin-ready long table from a wide abundance matrix."""
    wide_df = abundance_matrix.copy().reset_index().rename(columns={abundance_matrix.index.name or "index": sample_col})
    long_df = wide_df.melt(id_vars=[sample_col], var_name="taxon_key", value_name="value")
    lookup_cols = [c for c in ["taxon_key", "rank", "name", "tax_id", "ileft", "iright"] if c in taxon_lookup_df.columns]
    maaslin_df = long_df.merge(taxon_lookup_df[lookup_cols].drop_duplicates(subset=["taxon_key"]), on="taxon_key", how="left")
    maaslin_df["metric"] = "counts"
    return maaslin_df[[c for c in [sample_col, "taxon_key", "rank", "name", "tax_id", "value", "metric", "ileft", "iright"] if c in maaslin_df.columns]]

