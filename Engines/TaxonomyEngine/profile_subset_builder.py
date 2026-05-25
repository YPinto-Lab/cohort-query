from __future__ import annotations

import pandas as pd

from Common.contracts.selectors import SampleSelector, SubsetCriteria, TaxaSelector
from .abundance_matrix import AbundanceMatrix
from .profile_subset import ProfileSubset


class ProfileSubsetBuilder:
    """Slices an AbundanceMatrix by clade and/or sample into a ProfileSubset."""

    def build(self, matrix: AbundanceMatrix, metadata_df: pd.DataFrame, criteria: SubsetCriteria) -> ProfileSubset:
        by_taxa = self._filter_taxa(matrix, criteria.taxa)
        profile_df = self._filter_samples(by_taxa, metadata_df, criteria.samples)
        return ProfileSubset(profile_df=profile_df, full_metadata_df=metadata_df)

    def _filter_taxa(self, matrix: AbundanceMatrix, selector: TaxaSelector | None) -> pd.DataFrame:
        if selector is None:
            return matrix.counts
        keys = self._clade_keys(matrix, selector)
        return matrix.counts[[c for c in matrix.counts.columns if c in keys]]

    def _clade_keys(self, matrix: AbundanceMatrix, selector: TaxaSelector) -> set[str]:
        taxa = matrix.taxa
        hits = taxa[(taxa["rank"] == selector.rank) & taxa["name"].isin(selector.names)]
        return set(hits["taxon_key"])

    def _filter_samples(self, profile_df: pd.DataFrame, metadata_df: pd.DataFrame, selector: SampleSelector | None) -> pd.DataFrame:
        if selector is None:
            return profile_df
        kept = metadata_df.loc[metadata_df[selector.column].isin(selector.values), "acc"]
        return profile_df[profile_df.index.isin(set(kept))]
