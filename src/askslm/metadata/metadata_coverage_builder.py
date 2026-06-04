from __future__ import annotations

import pandas as pd

from ._populated import populated_mask


class MetadataCoverageBuilder:
    """Builds a bioproject x key matrix of the fraction of samples populated."""

    def build(self, metadata_df: pd.DataFrame, discovered_keys: list[str]) -> pd.DataFrame:
        if not discovered_keys or "bioproject" not in metadata_df.columns:
            return pd.DataFrame(columns=["bioproject", *discovered_keys])
        grouped = metadata_df.groupby("bioproject")[discovered_keys]
        coverage = grouped.apply(lambda frame: self._fractions(frame, discovered_keys))
        return coverage.reset_index()

    def _fractions(self, frame: pd.DataFrame, keys: list[str]) -> pd.Series:
        return pd.Series({key: self._fraction(frame[key]) for key in keys})

    def _fraction(self, series: pd.Series) -> float:
        return round(float(populated_mask(series).mean()), 3)
