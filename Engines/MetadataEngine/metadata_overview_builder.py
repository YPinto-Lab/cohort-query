from __future__ import annotations

import pandas as pd

from Common.contracts.metadata_results import MetadataOverview
from Common.contracts.sra_schema import SRAMetadataSchema
from .discovered_keys_builder import DiscoveredKeysBuilder
from .metadata_coverage_builder import MetadataCoverageBuilder
from .metadata_summary_builder import MetadataSummaryBuilder

_BASE_COLUMNS = set(SRAMetadataSchema.__fields__.keys())


class MetadataOverviewBuilder:
    """Summarizes an extracted metadata table into a MetadataOverview."""

    def __init__(self) -> None:
        self._summary = MetadataSummaryBuilder()
        self._keys = DiscoveredKeysBuilder()
        self._coverage = MetadataCoverageBuilder()

    def build(self, metadata_df: pd.DataFrame) -> MetadataOverview:
        discovered = self._discovered(metadata_df)
        return MetadataOverview(
            summary_df=self._summary.build(metadata_df, discovered),
            projects_df=self._projects(metadata_df),
            discovered_keys_df=self._keys.by_project(metadata_df, discovered),
            discovered_keys_unique_df=self._keys.unique(metadata_df, discovered),
            coverage_matrix_df=self._coverage.build(metadata_df, discovered),
        )

    def _discovered(self, metadata_df: pd.DataFrame) -> list[str]:
        return sorted(c for c in metadata_df.columns if c not in _BASE_COLUMNS and c != "acc")

    def _projects(self, metadata_df: pd.DataFrame) -> pd.DataFrame:
        if "bioproject" not in metadata_df.columns:
            return pd.DataFrame(columns=["bioproject", "samples"])
        return metadata_df.groupby("bioproject", as_index=False).agg(samples=("acc", "count"))
