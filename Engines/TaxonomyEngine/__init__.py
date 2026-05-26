from __future__ import annotations

from pathlib import Path

import pandas as pd

from Accessors.TaxonomyAccessor.taxonomy_file_accessor import TaxonomyFileAccessor
from Accessors.MergedDumpAccessor.merged_dump_accessor import MergedDumpAccessor
from Common.contracts.taxonomy_results import ResolutionSummary, ResolvedTaxonomy
from Engines.MetadataEngine.metadata import Metadata
from .abundance_matrix import AbundanceMatrix
from .abundance_matrix_builder import AbundanceMatrixBuilder
from .cohort import Cohort
from .taxonomy_resolver import TaxonomyResolver

DEFAULT_MERGED_DMP = Path(__file__).parent.parent.parent / "Accessors" / "TaxonomyAccessor" / "merged.dmp"


def load(source: str | Path) -> pd.DataFrame:
    return TaxonomyFileAccessor().read(Path(source))


def resolve(taxonomy_df: pd.DataFrame, merged_dmp: str | Path = DEFAULT_MERGED_DMP) -> ResolvedTaxonomy:
    mapping = MergedDumpAccessor().load(Path(merged_dmp))
    resolver = TaxonomyResolver(mapping)
    summary_dict, changes_df = resolver.summarize_resolution(taxonomy_df)
    return ResolvedTaxonomy(
        df=resolver.resolve(taxonomy_df),
        changes_df=changes_df,
        summary=_to_summary(summary_dict),
    )


def build_abundance_matrix(taxonomy_df: pd.DataFrame, rank: str = "genus") -> AbundanceMatrix:
    return AbundanceMatrixBuilder().build(taxonomy_df, rank)


def build_cohort(matrix: AbundanceMatrix, metadata: Metadata) -> Cohort:
    return Cohort(matrix=matrix, metadata=metadata)


def _to_summary(summary_dict: dict) -> ResolutionSummary:
    return ResolutionSummary(
        input_rows=summary_dict["input_rows"],
        rows_updated=summary_dict["rows_updated"],
        unique_old_tax_ids_updated=summary_dict["unique_old_tax_ids_updated"],
    )
