"""
Pure alpha diversity computation functions.

These functions are the computation core extracted from AlphaDiversityManager,
usable both from the Jupyter notebook manager and from the CLI.
"""
import numpy as np
import pandas as pd
from typing import Optional
from pathlib import Path

from Accessors.TaxonomyAccessor import TaxonomyAccessor
from Engines.DownstreamAnalysis.AlphaDiversity.alpha_diversity_engine import (
    AlphaDiversityEngine,
    STANDARD_RANKS,
)


def compute_alpha_diversity_metrics(
    taxonomy_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    rank: str,
    group_col: Optional[str] = None,
    filter_rank: Optional[str] = None,
    filter_taxon: Optional[str] = None,
    lineage_db_path: Optional[str] = None,
) -> pd.DataFrame:
    """
    Compute per-sample richness and Shannon index.

    Args:
        taxonomy_df: Taxonomy DataFrame (many rows per acc, one per taxon).
        metadata_df: Enriched metadata DataFrame (1 row per acc).
        rank: Taxonomic rank at which to count unique taxa (e.g. 'genus').
        group_col: Optional column in metadata_df to include in the result
                   for downstream grouping/plotting.
        filter_rank: Optional rank to filter taxonomy by before computing
                     (e.g. 'superkingdom').
        filter_taxon: Taxon name at filter_rank to keep (e.g. 'Bacteria').
                      Ignored if filter_rank is None.
        lineage_db_path: Optional path to prebuilt taxonomy lineage DB.

    Returns:
        DataFrame with columns: acc, richness, shannon, [group_col].
        All samples from taxonomy_df appear; samples with no taxa after
        filtering get richness=0 and shannon=0.0.
    """
    all_samples = taxonomy_df['acc'].unique()
    working_df = taxonomy_df.copy()

    tax_accessor: Optional[TaxonomyAccessor] = None
    if lineage_db_path:
        tax_accessor = TaxonomyAccessor(lineage_db_path=Path(lineage_db_path))

    # Apply optional taxon filter
    if filter_rank and filter_taxon:
        if tax_accessor is None:
            tax_accessor = TaxonomyAccessor()
            tax_accessor.build_from_dataframe(taxonomy_df)

        matching_tax_ids: set = set()
        for tax_id, lineage in tax_accessor.database.items():
            for ancestor in lineage:
                if (ancestor.get('rank', '').lower() == filter_rank.lower()
                        and ancestor.get('name', '') == filter_taxon):
                    matching_tax_ids.add(str(tax_id))
                    break

        working_df = working_df[working_df['tax_id'].astype(str).isin(matching_tax_ids)]

    # Count diversity only from rows already at the requested rank.
    # This avoids introducing synthetic "Unclassified (<rank>)" buckets from
    # higher/lower ranks that were not requested by the analysis.
    rank_df = working_df[working_df['rank'].astype(str).str.lower() == rank.lower()].copy()

    # Build (or rebuild) TaxonomyAccessor on rank-filtered data.
    if tax_accessor is None:
        tax_accessor = TaxonomyAccessor()
        tax_accessor.build_from_dataframe(rank_df if not rank_df.empty else taxonomy_df)

    if rank_df.empty:
        diversity_df = pd.DataFrame({'acc': all_samples, 'richness': 0, 'shannon': 0.0})
    else:
        aggregated_df = tax_accessor.aggregate_counts_at_rank(
            rank_df,
            target_rank=rank,
            tax_id_col='tax_id',
            count_col='total_count',
            sample_col='acc',
        )

        rows = []
        for sample, group in aggregated_df.groupby('sample'):
            counts = group['count'].values
            rows.append({
                'acc': sample,
                'richness': AlphaDiversityEngine.calculate_richness(counts),
                'shannon': AlphaDiversityEngine.calculate_shannon(counts),
            })
        diversity_df = pd.DataFrame(rows)

    # Ensure every sample is present (fill zeros for samples with no matching taxa)
    all_samples_df = pd.DataFrame({'acc': all_samples})
    diversity_df = all_samples_df.merge(diversity_df, on='acc', how='left')
    diversity_df['richness'] = diversity_df['richness'].fillna(0).astype(int)
    diversity_df['shannon'] = diversity_df['shannon'].fillna(0.0)

    # Attach grouping column from metadata if requested
    if group_col and group_col in metadata_df.columns:
        group_lookup = metadata_df[['acc', group_col]].drop_duplicates()
        diversity_df = diversity_df.merge(group_lookup, on='acc', how='left')

    return diversity_df


def compute_alpha_diversity(*args, **kwargs) -> pd.DataFrame:
    """Backward-compatible alias for compute_alpha_diversity_metrics."""
    return compute_alpha_diversity_metrics(*args, **kwargs)
