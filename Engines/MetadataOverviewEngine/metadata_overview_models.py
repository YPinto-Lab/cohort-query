"""Data transfer objects for metadata overview engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class MetadataOverviewResult:
    """Result of metadata overview analysis."""

    summary_df: pd.DataFrame
    projects_df: pd.DataFrame
    discovered_by_project_df: pd.DataFrame
    discovered_unique_df: pd.DataFrame
    metadata_matrix_df: pd.DataFrame

