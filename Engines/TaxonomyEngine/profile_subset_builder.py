from __future__ import annotations

import pandas as pd

from Common.contracts.selectors import SampleSelector, FilterCriteria, TaxaSelector
from .abundance_matrix import AbundanceMatrix
from .profile_subset import ProfileSubset


class ProfileSubsetBuilder:
    """Slices an AbundanceMatrix by clade and/or sample into a ProfileSubset."""

    def build(self, matrix: AbundanceMatrix, metadata_df: pd.DataFrame, criteria: FilterCriteria) -> ProfileSubset:
        by_taxa = self._filter_taxa(matrix, criteria.taxa)
        selectors = [s for s in (criteria.samples, *criteria.sample_filters) if s is not None]
        profile_df = self._apply_sample_filters(by_taxa, metadata_df, selectors)
        return ProfileSubset(profile_df=profile_df, full_metadata_df=metadata_df)

    def _filter_taxa(self, matrix: AbundanceMatrix, selector: TaxaSelector | None) -> pd.DataFrame:
        if selector is None:
            return matrix.counts
        keys = self._clade_keys(matrix, selector)
        return matrix.counts[[c for c in matrix.counts.columns if c in keys]]

    def _clade_keys(self, matrix: AbundanceMatrix, selector: TaxaSelector) -> set[str]:
        taxa = matrix.taxa
        hits = taxa[taxa[selector.rank].isin(selector.names)]
        return set(hits["taxon_key"])

    def _apply_sample_filters(self, profile_df: pd.DataFrame, metadata_df: pd.DataFrame, selectors: list[SampleSelector]) -> pd.DataFrame:
        result = profile_df
        for selector in selectors:
            result = self._filter_by_selector(result, metadata_df, selector)
        return result

    def _filter_by_selector(self, profile_df: pd.DataFrame, metadata_df: pd.DataFrame, selector: SampleSelector) -> pd.DataFrame:
        kept = metadata_df.loc[metadata_df[selector.column].isin(selector.values), "acc"]
        return profile_df[profile_df.index.isin(set(kept))]
