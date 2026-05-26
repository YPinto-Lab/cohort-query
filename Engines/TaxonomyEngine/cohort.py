from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from Common.contracts.selectors import FilterCriteria, SampleSelector, TaxaSelector
from Engines.MetadataEngine.metadata import Metadata
from .abundance_matrix import AbundanceMatrix


@dataclass(frozen=True, eq=False)
class Cohort:
    matrix: AbundanceMatrix
    metadata: Metadata

    def __post_init__(self) -> None:
        aligned = self.metadata.reindex_to(self.matrix.counts.index)
        object.__setattr__(self, "metadata", aligned)

    def filter(self, criteria: FilterCriteria) -> Cohort:
        new_matrix = self._filter_taxa(self.matrix, criteria.taxa)
        sample_selectors = [s for s in (criteria.samples, *criteria.sample_filters) if s is not None]
        new_metadata = self._filter_metadata(self.metadata, sample_selectors)
        new_matrix = self._reindex_matrix_rows(new_matrix, list(new_metadata.df["acc"]))
        return Cohort(matrix=new_matrix, metadata=new_metadata)

    def write(self, out_dir: Path, fmt: str = "counts") -> list[Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        matrix_path = self.matrix.write(out_dir / "abundance_matrix.csv", fmt)
        metadata_path = self.metadata.write(out_dir / "metadata.csv")
        return [matrix_path, metadata_path]

    @staticmethod
    def _filter_taxa(matrix: AbundanceMatrix, selector: TaxaSelector | None) -> AbundanceMatrix:
        if selector is None:
            return matrix
        taxa = matrix.taxa
        keys = set(taxa[taxa[selector.rank].isin(selector.names)]["taxon_key"])
        kept_columns = [c for c in matrix.counts.columns if c in keys]
        new_counts = matrix.counts[kept_columns]
        return AbundanceMatrix(counts=new_counts, lookup=matrix._lookup, lineage_df=matrix._lineage_df)

    @staticmethod
    def _filter_metadata(metadata: Metadata, selectors: list[SampleSelector]) -> Metadata:
        result = metadata
        for selector in selectors:
            result = result.filter(selector)
        return result

    @staticmethod
    def _reindex_matrix_rows(matrix: AbundanceMatrix, sample_ids: list[str]) -> AbundanceMatrix:
        present = [acc for acc in sample_ids if acc in matrix.counts.index]
        new_counts = matrix.counts.reindex(present)
        return AbundanceMatrix(counts=new_counts, lookup=matrix._lookup, lineage_df=matrix._lineage_df)
