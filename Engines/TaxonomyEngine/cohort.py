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
        aligned = self.metadata.reindex_to(self.matrix.matrix.index)
        object.__setattr__(self, "metadata", aligned)

    def filter(self, criteria: FilterCriteria) -> Cohort:
        new_matrix = self._filter_taxa(self.matrix, criteria.taxa)
        sample_selectors = [s for s in (criteria.samples, *criteria.sample_filters) if s is not None]
        new_metadata = self._filter_metadata(self.metadata, sample_selectors)
        new_matrix = new_matrix.filter(new_metadata.df["acc"])
        return Cohort(matrix=new_matrix, metadata=new_metadata)

    def write(self, out_dir: Path, fmt: str = "counts") -> list[Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        matrix_path = self.matrix.write(out_dir / "abundance_matrix.csv", fmt)
        metadata_path = self.metadata.write(out_dir / "metadata.csv")
        return [matrix_path, metadata_path]

    @property
    def n_samples(self) -> int:
        return self.matrix.matrix.shape[0]

    @property
    def n_taxa(self) -> int:
        return self.matrix.matrix.shape[1]

    def unique(self, column: str) -> list[str]:
        self._require_column(column)
        return sorted(self.metadata.df[column].dropna().unique().tolist())

    def enrich(self, extras: pd.DataFrame, *, left_on: str, right_on: str) -> Cohort:
        self._require_column(left_on)
        self._require_extras_column(extras, right_on)
        merged_metadata = self._merged_metadata(extras, left_on, right_on)
        return Cohort(matrix=self.matrix, metadata=merged_metadata)

    def _require_column(self, column: str) -> None:
        if column in self.metadata.df.columns:
            return
        raise ValueError(f"Column '{column}' not found in cohort metadata")

    def _require_extras_column(self, extras: pd.DataFrame, column: str) -> None:
        if column in extras.columns:
            return
        raise ValueError(f"Column '{column}' not found in extras")

    def _merged_metadata(self, extras: pd.DataFrame, left_on: str, right_on: str) -> Metadata:
        deduped = extras.drop_duplicates(subset=[right_on])
        joined = self.metadata.df.merge(deduped, left_on=left_on, right_on=right_on, how="left")
        if right_on == left_on:
            return Metadata(df=joined)
        return Metadata(df=joined.drop(columns=[right_on]))

    def split_by(self, column: str) -> dict[str, Cohort]:
        self._require_column(column)
        column_unique_values = self.unique(column)

        def by(value: str):
            return FilterCriteria(sample_filters=(SampleSelector(column, (value,)),))

        result = {value: self.filter(by(value)) for value in column_unique_values}
        return result

    @staticmethod
    def _filter_taxa(matrix: AbundanceMatrix, selector: TaxaSelector | None) -> AbundanceMatrix:
        if selector is None:
            return matrix
        taxa = matrix.taxa_lineage
        keys = set(taxa[taxa[selector.rank].isin(selector.names)]["taxon_key"])
        kept_columns = [c for c in matrix.matrix.columns if c in keys]
        new_matrix = matrix.matrix[kept_columns]
        return AbundanceMatrix(
            matrix=new_matrix,
            total_reads=matrix.total_reads,
            taxon_key_lookup=matrix._taxon_key_lookup,
            tax_id_lineage_lookup=matrix._tax_id_lineage_lookup,
        )

    @staticmethod
    def _filter_metadata(metadata: Metadata, selectors: list[SampleSelector]) -> Metadata:
        result = metadata
        for selector in selectors:
            result = result.filter(selector)
        return result

