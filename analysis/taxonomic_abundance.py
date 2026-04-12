"""
Pure taxonomic abundance computation functions.

Extracted from TaxonomicAbundanceManager for use in the CLI.
"""
import numpy as np
import pandas as pd
from typing import Optional, Tuple


def compute_taxonomic_abundance(
    taxonomy_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    rank: str,
    taxon: str,
    group_col: Optional[str] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compute per-sample relative abundance for a specific taxon.

    Args:
        taxonomy_df: Taxonomy DataFrame (many rows per acc, one per taxon).
        metadata_df: Enriched metadata DataFrame (1 row per acc).
        rank: Taxonomic rank of the target taxon (e.g. 'genus').
        taxon: Name of the taxon to compute abundance for (e.g. 'Prevotella').
        group_col: Optional column in metadata_df to include for grouping.

    Returns:
        Tuple of:
          - abundance_df: acc, total_sample_reads, taxon_reads,
                          relative_abundance, bioproject, [group_col]
          - summary_df: prevalence statistics per group (and 'All Combined')
    """
    rank_df = taxonomy_df[taxonomy_df['rank'].str.lower() == rank.lower()]
    total_counts = rank_df.groupby('acc')['total_count'].sum().rename('total_sample_reads')

    taxon_df = rank_df[rank_df['name'] == taxon]
    taxon_counts = taxon_df.groupby('acc')['total_count'].sum().rename('taxon_reads')

    all_samples = taxonomy_df[['acc']].drop_duplicates().set_index('acc')
    abundance_df = all_samples.join(total_counts).join(taxon_counts).fillna(0).reset_index()

    abundance_df['relative_abundance'] = np.where(
        abundance_df['total_sample_reads'] > 0,
        abundance_df['taxon_reads'] / abundance_df['total_sample_reads'],
        0.0,
    )

    # Attach bioproject and optional group column from metadata
    extra_cols = ['bioproject']
    if group_col and group_col not in extra_cols:
        extra_cols.append(group_col)
    valid_extras = [c for c in extra_cols if c in metadata_df.columns]
    if valid_extras:
        meta_join = metadata_df[['acc'] + valid_extras].drop_duplicates()
        abundance_df = abundance_df.merge(meta_join, on='acc', how='left')

    # Prevalence summary
    def _summary_row(name: str, subset: pd.DataFrame) -> dict:
        n = len(subset)
        n_zero = (subset['taxon_reads'] == 0).sum()
        prevalence = (n - n_zero) / n if n > 0 else 0.0
        return {
            'Cohort': name,
            'Total Samples (N)': n,
            'Samples with 0 Reads': int(n_zero),
            'Samples with Non-Zero Reads (%)': f"{prevalence:.2%}",
            'Mean Rel. Abundance': f"{subset['relative_abundance'].mean():.6%}",
        }

    summary_rows = []
    if group_col and group_col in abundance_df.columns:
        for group_name, group_data in abundance_df.groupby(group_col):
            summary_rows.append(_summary_row(str(group_name), group_data))
    summary_rows.append(_summary_row('All Combined', abundance_df))
    summary_df = pd.DataFrame(summary_rows)

    return abundance_df, summary_df
